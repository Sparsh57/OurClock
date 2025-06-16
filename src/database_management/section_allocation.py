import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from .dbconnection import get_db_session
from .models import User, Course, CourseStud
from sqlalchemy.exc import SQLAlchemyError
import logging
from sqlalchemy import func

logger = logging.getLogger(__name__)


def get_optimal_k(student_course_matrix, student_matrix, max_k=10):
    """
    Determine optimal number of clusters using silhouette score.
    
    :param student_course_matrix: DataFrame with students as rows and courses as columns
    :param student_matrix: Numpy array of the matrix
    :param max_k: Maximum number of clusters to consider
    :return: Optimal number of clusters
    """
    if len(student_course_matrix) < 2:
        return 1
    
    sil_scores = []
    K_range = range(2, min(max_k, len(student_course_matrix)))
    
    if len(K_range) == 0:
        return 1

    for k in K_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(student_matrix)
        sil_scores.append(silhouette_score(student_matrix, labels))

    optimal_k_value = K_range[np.argmax(sil_scores)]
    return optimal_k_value


def get_multi_section_courses(db_path):
    """
    Get courses that have multiple sections.
    
    :param db_path: Path to the database
    :return: Dictionary mapping course names to number of sections
    """
    with get_db_session(db_path) as session:
        try:
            courses = session.query(Course).filter(Course.NumberOfSections > 1).all()
            return {course.CourseName: course.NumberOfSections for course in courses}
        except SQLAlchemyError as e:
            logger.error(f"Error fetching multi-section courses: {e}")
            return {}


def create_student_course_matrix(db_path):
    """
    Create a student-course matrix for clustering analysis.
    
    :param db_path: Path to the database
    :return: DataFrame with students as rows and courses as columns (pivot table)
    """
    with get_db_session(db_path) as session:
        try:
            # Get all student enrollments
            query = session.query(
                User.Email.label('Roll_No'),
                Course.CourseName.label('G_CODE')
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')
            
            df = pd.DataFrame(query.all())
            
            if df.empty:
                logger.warning("No student enrollment data found")
                return pd.DataFrame()
            
            # Extract base course names from section identifiers if they exist in G_CODE
            def extract_base_course(course_identifier):
                """Extract base course name from section identifier like DATA201-A -> DATA201"""
                if '-' in course_identifier and course_identifier.split('-')[-1].isalpha():
                    parts = course_identifier.split('-')
                    if len(parts[-1]) == 1:  # Single letter section identifier
                        return '-'.join(parts[:-1])
                return course_identifier
            
            df['BaseCourse'] = df['G_CODE'].apply(extract_base_course)
            
            # Create pivot table using base course names
            student_course_matrix = df.pivot_table(
                index="Roll_No", 
                columns="BaseCourse", 
                aggfunc=lambda x: 1, 
                fill_value=0
            )
            
            # Flatten column index if it's a MultiIndex
            if isinstance(student_course_matrix.columns, pd.MultiIndex):
                student_course_matrix.columns = student_course_matrix.columns.get_level_values(-1)
            
            return student_course_matrix
            
        except SQLAlchemyError as e:
            logger.error(f"Error creating student-course matrix: {e}")
            return pd.DataFrame()


def allocate_sections_for_course(course_name, num_sections, enrolled_students_df, max_section_size=None):
    """
    Allocate students to sections for a specific course using clustering.
    
    :param course_name: Name of the course
    :param num_sections: Number of sections for the course
    :param enrolled_students_df: DataFrame with students enrolled in this course
    :param max_section_size: Maximum students per section (calculated if None)
    :return: List of dictionaries with section assignments
    """
    if enrolled_students_df.empty:
        return []
    
    enrolled_students = enrolled_students_df.reset_index()[["Roll_No", "Cluster"]]
    
    if max_section_size is None:
        max_section_size = max(10, len(enrolled_students) // num_sections)
    
    section_assignments = []
    section_counter = 1
    
    # Group students by cluster
    grouped_students = enrolled_students.groupby("Cluster")["Roll_No"].apply(list)
    
    for cluster, students in grouped_students.items():
        cluster_size = len(students)
        
        # If cluster fits in one section, assign all to same section
        if cluster_size <= max_section_size:
            for student in students:
                section_assignments.append({
                    "Roll_No": student,
                    "Course": course_name,
                    "Cluster": cluster,
                    "Assigned_Section": section_counter
                })
            section_counter = (section_counter % num_sections) + 1
        
        # If cluster is too large, split across sections
        else:
            num_splits = min(num_sections, (cluster_size // max_section_size) + (1 if cluster_size % max_section_size != 0 else 0))
            students_per_section = cluster_size // num_splits
            
            for i in range(num_splits):
                start_idx = i * students_per_section
                end_idx = (i + 1) * students_per_section if i < num_splits - 1 else cluster_size
                assigned_students = students[start_idx:end_idx]
                
                for student in assigned_students:
                    section_assignments.append({
                        "Roll_No": student,
                        "Course": course_name,
                        "Cluster": cluster,
                        "Assigned_Section": section_counter
                    })
                
                section_counter = (section_counter % num_sections) + 1
    
    return section_assignments


def allocate_all_sections(db_path):
    """
    Allocate students to sections for all multi-section courses.
    
    :param db_path: Path to the database
    :return: List of all section assignments
    """
    logger.info("Starting section allocation process")
    
    # Create student-course matrix
    student_course_matrix = create_student_course_matrix(db_path)
    
    if student_course_matrix.empty:
        logger.warning("No student-course data available for section allocation")
        return []
    
    # Convert to numpy for clustering
    student_matrix = student_course_matrix.to_numpy()
    
    # Find optimal number of clusters
    optimal_k = get_optimal_k(student_course_matrix, student_matrix)
    logger.info(f"Optimal number of clusters: {optimal_k}")
    
    # Run KMeans clustering
    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    student_clusters = kmeans.fit_predict(student_matrix)
    
    # Add cluster information to the matrix
    student_course_matrix["Cluster"] = student_clusters
    
    # Get multi-section courses
    multi_section_courses = get_multi_section_courses(db_path)
    
    all_section_assignments = []
    
    # Allocate sections for each multi-section course
    for course_name, num_sections in multi_section_courses.items():
        logger.info(f"Allocating sections for course {course_name} ({num_sections} sections)")
        
        # Get students enrolled in this course
        enrolled_students = student_course_matrix[student_course_matrix[course_name] == 1]
        
        # Allocate sections for this course
        course_assignments = allocate_sections_for_course(
            course_name, num_sections, enrolled_students
        )
        
        all_section_assignments.extend(course_assignments)
        logger.info(f"Allocated {len(course_assignments)} students to sections for {course_name}")
    
    return all_section_assignments


def update_student_sections_in_db(section_assignments, db_path):
    """
    Update the database with section assignments.
    
    :param section_assignments: List of section assignment dictionaries
    :param db_path: Path to the database
    """
    with get_db_session(db_path) as session:
        try:
            for assignment in section_assignments:
                # Get student and course IDs
                student = session.query(User).filter_by(Email=assignment["Roll_No"]).first()
                course = session.query(Course).filter_by(CourseName=assignment["Course"]).first()
                
                if student and course:
                    # Update the CourseStud entry with section number
                    enrollment = session.query(CourseStud).filter_by(
                        StudentID=student.UserID,
                        CourseID=course.CourseID
                    ).first()
                    
                    if enrollment:
                        enrollment.SectionNumber = assignment["Assigned_Section"]
                        logger.debug(f"Assigned student {assignment['Roll_No']} to section {assignment['Assigned_Section']} of {assignment['Course']}")
            
            session.commit()
            logger.info(f"Updated {len(section_assignments)} section assignments in database")
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating section assignments: {e}")
            raise


def print_section_assignments(section_assignments, title="Section Assignments"):
    """
    Print section assignments in a formatted table.
    
    :param section_assignments: List of section assignment dictionaries
    :param title: Title for the output
    """
    if not section_assignments:
        print("No section assignments to display.")
        return
    
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}")
    
    # Group assignments by course
    course_assignments = {}
    for assignment in section_assignments:
        course_name = assignment["Course"]
        if course_name not in course_assignments:
            course_assignments[course_name] = {}
        
        section_num = assignment["Assigned_Section"]
        if section_num not in course_assignments[course_name]:
            course_assignments[course_name][section_num] = []
        
        course_assignments[course_name][section_num].append(assignment["Roll_No"])
    
    # Print assignments for each course
    for course_name in sorted(course_assignments.keys()):
        print(f"\n📚 Course: {course_name}")
        print("-" * 50)
        
        sections = course_assignments[course_name]
        for section_num in sorted(sections.keys()):
            students = sorted(sections[section_num])
            print(f"  Section {section_num} ({len(students)} students):")
            
            # Print students in columns for better readability
            students_per_row = 3
            for i in range(0, len(students), students_per_row):
                student_group = students[i:i + students_per_row]
                formatted_students = [f"    • {student:<20}" for student in student_group]
                print("".join(formatted_students))
        
        # Print section summary
        total_students = sum(len(students) for students in sections.values())
        print(f"  📊 Total students in {course_name}: {total_students}")
    
    print(f"\n{'='*60}")
    total_assignments = len(section_assignments)
    total_courses = len(course_assignments)
    print(f"📈 Summary: {total_assignments} students assigned across {total_courses} courses")
    print(f"{'='*60}")


def print_detailed_section_mapping(db_path):
    """
    Print detailed section mapping from the database including cluster information.
    
    :param db_path: Path to the database
    """
    with get_db_session(db_path) as session:
        try:
            # Get detailed student section information
            query = session.query(
                User.Email.label('Roll_No'),
                User.Name.label('Student_Name'),
                Course.CourseName.label('Course'),
                Course.NumberOfSections,
                CourseStud.SectionNumber
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')\
             .filter(Course.NumberOfSections > 1)\
             .order_by(Course.CourseName, CourseStud.SectionNumber, User.Email)
            
            df = pd.DataFrame(query.all())
            
            if df.empty:
                print("\n🔍 No multi-section courses found in the database.")
                return
            
            print(f"\n{'='*80}")
            print(f"{'DETAILED STUDENT-SECTION MAPPING':^80}")
            print(f"{'='*80}")
            
            # Group by course
            for course_name in df['Course'].unique():
                course_data = df[df['Course'] == course_name]
                num_sections = course_data['NumberOfSections'].iloc[0]
                
                print(f"\n📚 Course: {course_name} ({num_sections} sections)")
                print("-" * 70)
                
                # Group by section
                for section_num in sorted(course_data['SectionNumber'].unique()):
                    section_students = course_data[course_data['SectionNumber'] == section_num]
                    print(f"\n  🏫 Section {section_num} ({len(section_students)} students):")
                    
                    # Print students with names if available
                    for _, student in section_students.iterrows():
                        student_name = student['Student_Name'] if student['Student_Name'] != student['Roll_No'] else "N/A"
                        print(f"    • {student['Roll_No']:<25} ({student_name})")
                
                # Print course statistics
                print(f"\n  📊 Course Statistics:")
                section_counts = course_data.groupby('SectionNumber').size()
                for section_num, count in section_counts.items():
                    print(f"    - Section {section_num}: {count} students")
                
                avg_section_size = len(course_data) / num_sections
                print(f"    - Average section size: {avg_section_size:.1f} students")
            
            print(f"\n{'='*80}")
            
        except SQLAlchemyError as e:
            logger.error(f"Error printing detailed section mapping: {e}")


def export_section_mapping_to_csv(db_path, filename=None):
    """
    Export student section mapping to a CSV file.
    
    :param db_path: Path to the database
    :param filename: Output filename (auto-generated if None)
    :return: Filename of the exported CSV
    """
    if filename is None:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"student_section_mapping_{timestamp}.csv"
    
    with get_db_session(db_path) as session:
        try:
            query = session.query(
                User.Email.label('Roll_No'),
                User.Name.label('Student_Name'),
                Course.CourseName.label('Course'),
                Course.NumberOfSections,
                CourseStud.SectionNumber
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')\
             .order_by(Course.CourseName, CourseStud.SectionNumber, User.Email)
            
            df = pd.DataFrame(query.all())
            
            if not df.empty:
                # Add a formatted course-section identifier
                df['Course_Section'] = df.apply(
                    lambda row: f"{row['Course']}-{chr(ord('A') + row['SectionNumber'] - 1)}" 
                    if row['NumberOfSections'] > 1 else row['Course'], 
                    axis=1
                )
                
                # Reorder columns for better CSV output
                df = df[['Roll_No', 'Student_Name', 'Course', 'SectionNumber', 'Course_Section', 'NumberOfSections']]
                
                df.to_csv(filename, index=False)
                print(f"✅ Student section mapping exported to: {filename}")
                print(f"📊 Total records exported: {len(df)}")
                return filename
            else:
                print("❌ No student enrollment data found to export.")
                return None
                
        except SQLAlchemyError as e:
            logger.error(f"Error exporting section mapping: {e}")
            return None


def run_section_allocation(db_path, print_mapping=True, export_csv=False):
    """
    Main function to run the complete section allocation process.
    
    :param db_path: Path to the database
    :param print_mapping: Whether to print the section mapping after allocation
    :param export_csv: Whether to export the section mapping to CSV
    :return: List of section assignments
    """
    try:
        # Generate section assignments
        section_assignments = allocate_all_sections(db_path)
        
        if section_assignments:
            # Update database with assignments
            update_student_sections_in_db(section_assignments, db_path)
            logger.info("Section allocation completed successfully")
            
            # Print section assignments if requested
            if print_mapping:
                print_section_assignments(section_assignments, "🎯 Section Allocation Results")
                print_detailed_section_mapping(db_path)
            
            # Export to CSV if requested
            if export_csv:
                export_section_mapping_to_csv(db_path)
                
        else:
            logger.info("No section assignments needed")
            if print_mapping:
                print("\n🔍 No multi-section courses found - no section allocation needed.")
        
        return section_assignments
        
    except Exception as e:
        logger.error(f"Error in section allocation process: {e}")
        raise


def get_section_allocation_summary(db_path):
    """
    Get a summary of section allocation statistics.
    
    :param db_path: Path to the database
    :return: Dictionary with allocation summary
    """
    with get_db_session(db_path) as session:
        try:
            # Get multi-section courses and their enrollments
            query = session.query(
                Course.CourseName,
                Course.NumberOfSections,
                CourseStud.SectionNumber,
                func.count(CourseStud.StudentID).label('StudentCount')
            ).select_from(Course)\
             .join(CourseStud, Course.CourseID == CourseStud.CourseID)\
             .filter(Course.NumberOfSections > 1)\
             .group_by(Course.CourseName, Course.NumberOfSections, CourseStud.SectionNumber)\
             .order_by(Course.CourseName, CourseStud.SectionNumber)
            
            results = query.all()
            
            summary = {
                'total_multi_section_courses': 0,
                'total_sections': 0,
                'total_students_in_sections': 0,
                'courses': {},
                'section_size_stats': {
                    'min': float('inf'),
                    'max': 0,
                    'avg': 0
                }
            }
            
            section_sizes = []
            
            for row in results:
                course_name = row.CourseName
                if course_name not in summary['courses']:
                    summary['courses'][course_name] = {
                        'num_sections': row.NumberOfSections,
                        'sections': {}
                    }
                    summary['total_multi_section_courses'] += 1
                
                summary['courses'][course_name]['sections'][row.SectionNumber] = row.StudentCount
                summary['total_sections'] += 1
                summary['total_students_in_sections'] += row.StudentCount
                section_sizes.append(row.StudentCount)
            
            if section_sizes:
                summary['section_size_stats']['min'] = min(section_sizes)
                summary['section_size_stats']['max'] = max(section_sizes)
                summary['section_size_stats']['avg'] = sum(section_sizes) / len(section_sizes)
            else:
                summary['section_size_stats'] = {'min': 0, 'max': 0, 'avg': 0}
            
            return summary
            
        except SQLAlchemyError as e:
            logger.error(f"Error getting section allocation summary: {e}")
            return {}


def print_section_allocation_summary(db_path):
    """
    Print a formatted summary of section allocation.
    
    :param db_path: Path to the database
    """
    summary = get_section_allocation_summary(db_path)
    
    if not summary or not summary['courses']:
        print("\n🔍 No multi-section courses found in the database.")
        return
    
    print(f"\n{'='*70}")
    print(f"{'📊 SECTION ALLOCATION SUMMARY':^70}")
    print(f"{'='*70}")
    
    print(f"📚 Multi-section courses: {summary['total_multi_section_courses']}")
    print(f"🏫 Total sections: {summary['total_sections']}")
    print(f"👥 Total students in sections: {summary['total_students_in_sections']}")
    
    stats = summary['section_size_stats']
    print(f"📈 Section size - Min: {stats['min']}, Max: {stats['max']}, Avg: {stats['avg']:.1f}")
    
    print(f"\n{'Course Details':^70}")
    print("-" * 70)
    
    for course_name, course_data in summary['courses'].items():
        print(f"\n📚 {course_name} ({course_data['num_sections']} sections):")
        for section_num, student_count in course_data['sections'].items():
            print(f"  Section {section_num}: {student_count} students")
        
        total_students = sum(course_data['sections'].values())
        avg_size = total_students / course_data['num_sections']
        print(f"  📊 Total: {total_students} students (avg: {avg_size:.1f} per section)")
    
    print(f"\n{'='*70}") 
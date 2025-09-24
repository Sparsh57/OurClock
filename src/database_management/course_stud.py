from .dbconnection import get_db_session, create_tables
from .models import User, Course, CourseStud
from .section_allocation import run_section_allocation, print_detailed_section_mapping, export_section_mapping_to_csv, print_section_allocation_summary
from .migration import migrate_database_for_sections, check_migration_needed
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def find_matching_course_pattern(individual_course, course_dict):
    """
    Find which course pattern in the database matches the individual course code.
    Treats courses with parenthetical suffixes as individual courses.
    
    Examples:
    - individual_course = "COMP208|DATA208(A)", course_dict contains "COMP208|DATA208(A)" -> exact match
    - individual_course = "COMP208|DATA208(B)", course_dict contains "COMP208|DATA208(B)" -> exact match  
    - individual_course = "HIST330", course_dict contains "HIST330|SOCL330|POLT330" -> pattern match
    
    :param individual_course: Course code from student enrollment (e.g., "COMP208|DATA208(A)")
    :param course_dict: Dictionary mapping course patterns to course IDs
    :return: (course_pattern, course_id) tuple if found, None otherwise
    """
    # First, try exact match - this handles individual courses including those with sections
    if individual_course in course_dict:
        return (individual_course, course_dict[individual_course])
    
    # If no exact match and the course has parentheses, try matching without the suffix
    # This is for backward compatibility with courses that might not have section suffixes in the database
    if "(" in individual_course and ")" in individual_course:
        base_course = individual_course.split("(")[0].strip()
        if base_course in course_dict:
            return (base_course, course_dict[base_course])
    
    # Look for the individual course within complex patterns with | or &
    for course_pattern, course_id in course_dict.items():
        # Check if the individual course is part of this pattern
        if '|' in course_pattern or '&' in course_pattern:
            # Split by both | and & to get all course components
            pattern_parts = course_pattern.replace('&', '|').split('|')
            pattern_courses = [part.strip() for part in pattern_parts]
            
            # Check if individual_course matches any part exactly
            if individual_course in pattern_courses:
                return (course_pattern, course_id)
            
            # Also check if individual_course matches any part when we remove parenthetical suffixes
            base_individual = individual_course.split('(')[0].strip() if '(' in individual_course else individual_course
            for pattern_course in pattern_courses:
                # Remove parenthetical suffix like "(A)" from "COURSE123(A)"
                base_pattern_course = pattern_course.split('(')[0].strip() if '(' in pattern_course else pattern_course
                if base_individual == base_pattern_course:
                    return (course_pattern, course_id)
    
    return None


def insert_course_students(file, db_path):
    """
    Inserts student course enrollments using bulk operations.
    Includes section allocation for multi-section courses.

    :param file: The CSV file containing student registration data.
    :param db_path: Path to the database file or schema identifier.
    """
    df_courses = file
    print(f"Bulk inserting course students into database: {db_path}")

    from .dbconnection import is_postgresql, get_organization_database_url
    
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Check if migration is needed and run it (only for SQLite)
    if not is_postgresql() and check_migration_needed(db_path):
        print("Database migration needed for sections support...")
        migrate_database_for_sections(db_path)
        print("Database migration completed.")

    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Course_Stud table exists by querying it
                session.execute(text("SELECT 1 FROM \"Course_Stud\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Course_Stud table exists by querying it
                session.execute(text("SELECT 1 FROM Course_Stud LIMIT 1"))
    except Exception:
        # If table doesn't exist, create all tables
        logger.info("Course_Stud table not found, creating tables...")
        if is_postgresql() and org_name:
            create_tables(get_organization_database_url(), org_name)
        else:
            create_tables(db_path)
        logger.info("Tables created successfully")

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Fetch user information (UserID and Email) for students
            students = session.query(User).filter_by(Role='Student').all()
            student_dict = {student.Email: student.UserID for student in students}

            # Fetch available courses (CourseID and CourseName) - these contain complex patterns
            courses = session.query(Course).all()
            course_dict = {course.CourseName: course.CourseID for course in courses}

            print(f"Found {len(course_dict)} courses in database:")
            for course_name in list(course_dict.keys())[:10]:  # Show first 10 courses
                print(f"  - {course_name}")
            if len(course_dict) > 10:
                print(f"  ... and {len(course_dict) - 10} more")

            # Create a new DataFrame with relevant columns (G CODE and Roll No.)
            df_merged = df_courses[['G CODE', 'Roll No.', 'Sections']].copy()
            
            # Prepare data for bulk insert
            enrollments_to_insert = []
            courses_not_found = set()
            successful_enrollments = 0

            # Process enrollments
            for index, row in df_merged.iterrows():
                try:
                    g_code = row["G CODE"]
                    roll_no = row["Roll No."]
                    section = row["Sections"]
                    
                    # Get student ID
                    student_id = student_dict.get(roll_no)
                    if not student_id:
                        continue

                    section_number = 1  # Default section

                    # Handle section information in G CODE
                    if "(" in g_code and ")" in g_code:
                        # For courses like "COMP208|DATA208(A)", treat the full string as the course name
                        # Don't parse it - it's already a complete course identifier
                        course = g_code.strip()
                    elif "-" in g_code and g_code.split("-")[-1].isalpha() and len(g_code.split("-")[-1]) == 1:
                        # Handle dash-separated format like "DATA201-A", "DATA201-B"
                        # These should also be treated as complete course identifiers
                        course = g_code.strip()
                    else:
                        # No section info in G CODE, use course as-is
                        course = g_code.strip()

                    # Find matching complex course pattern in database
                    course_match = find_matching_course_pattern(course, course_dict)
                    
                    if not course_match:
                        courses_not_found.add(course)
                        logger.warning(f"Course {course} not found in any database pattern")
                        continue

                    course_pattern, course_id = course_match
                    
                    # Add enrollment for the matched course
                    enrollments_to_insert.append({
                        'StudentID': student_id,
                        'CourseID': course_id,
                        'SectionNumber': section_number
                    })
                    successful_enrollments += 1

                except Exception as e:
                    logger.error(f"Error processing enrollment for G CODE {g_code}: {e}")
                    continue

            # Report on courses not found
            if courses_not_found:
                print(f"\n⚠️  {len(courses_not_found)} unique courses were not found in database:")
                for course in sorted(courses_not_found):
                    print(f"   - {course}")
            
            print(f"\n✅ Successfully processed {successful_enrollments} enrollments")

            # Get existing enrollments to avoid duplicates
            existing_enrollments = set()
            for enrollment in session.query(CourseStud).all():
                existing_enrollments.add((enrollment.StudentID, enrollment.CourseID))

            # Filter out existing enrollments
            new_enrollments = [
                enrollment for enrollment in enrollments_to_insert
                if (enrollment['StudentID'], enrollment['CourseID']) not in existing_enrollments
            ]

            # Bulk insert new enrollments
            if new_enrollments:
                session.bulk_insert_mappings(CourseStud, new_enrollments)
                session.commit()
                logger.info(f"Bulk inserted {len(new_enrollments)} course-student enrollments")
                print(f"Successfully bulk inserted {len(new_enrollments)} course-student enrollments.")
            else:
                logger.info("No new course-student enrollments to insert")
                print("No new course-student enrollments to insert.")

        except Exception as e:
            session.rollback()
            logger.error(f"Error bulk inserting course-student data: {e}")
            raise

    # After inserting enrollments, run section allocation for multi-section courses
    try:
        print("Running section allocation for multi-section courses...")
        section_assignments = run_section_allocation(db_path, print_mapping=True, export_csv=False)
        if section_assignments:
            print(f"Successfully allocated {len(section_assignments)} students to sections")
        else:
            print("No section allocation needed (no multi-section courses found)")
    except Exception as e:
        logger.error(f"Error in section allocation: {e}")
        print(f"Warning: Section allocation failed: {e}")


def get_student_section_info(db_path):
    """
    Retrieve student section assignments for all courses.
    
    :param db_path: Path to the database or schema identifier
    :return: DataFrame with student section information
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    from .dbconnection import is_postgresql, get_organization_database_url
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            query = session.query(
                User.Email.label('Roll_No'),
                User.Name.label('Student_Name'),
                Course.CourseName.label('Course'),
                CourseStud.SectionNumber
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')\
             .order_by(Course.CourseName, CourseStud.SectionNumber, User.Email)
            
            return pd.DataFrame(query.all())
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching student section info: {e}")
            return pd.DataFrame()


def print_student_section_mapping(db_path):
    """
    Print student section mapping for all courses.
    Wrapper function to call the detailed section mapping printer.
    
    :param db_path: Path to the database
    """
    print_detailed_section_mapping(db_path)


def export_student_section_mapping(db_path, filename=None):
    """
    Export student section mapping to CSV.
    Wrapper function to export section mapping.
    
    :param db_path: Path to the database
    :param filename: Output filename (auto-generated if None)
    :return: Filename of the exported CSV
    """
    return export_section_mapping_to_csv(db_path, filename)


def print_section_summary(db_path):
    """
    Print a summary of section allocation.
    Wrapper function to call the section allocation summary printer.
    
    :param db_path: Path to the database
    """
    print_section_allocation_summary(db_path)


def run_section_allocation_with_options(db_path, print_mapping=True, export_csv=False, print_summary=True):
    """
    Run section allocation with various output options.
    
    :param db_path: Path to the database
    :param print_mapping: Whether to print detailed section mapping
    :param export_csv: Whether to export section mapping to CSV
    :param print_summary: Whether to print allocation summary
    :return: List of section assignments
    """
    try:
        print("🚀 Starting section allocation with enhanced options...")
        
        # Run section allocation
        section_assignments = run_section_allocation(db_path, print_mapping=print_mapping, export_csv=export_csv)
        
        # Print summary if requested
        if print_summary and section_assignments:
            print_section_allocation_summary(db_path)
        
        return section_assignments
        
    except Exception as e:
        logger.error(f"Error in section allocation with options: {e}")
        raise


def get_section_mapping_dataframe(db_path):
    """
    Get student section mapping as a pandas DataFrame.
    Enhanced version of get_student_section_info with more details.
    
    :param db_path: Path to the database or schema identifier
    :return: DataFrame with comprehensive student section information
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    from .dbconnection import is_postgresql, get_organization_database_url
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            query = session.query(
                User.Email.label('Roll_No'),
                User.Name.label('Student_Name'),
                Course.CourseName.label('Course'),
                Course.NumberOfSections,
                CourseStud.SectionNumber,
                Course.CourseType.label('Course_Type'),
                Course.ClassesPerWeek
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')\
             .order_by(Course.CourseName, CourseStud.SectionNumber, User.Email)
            
            df = pd.DataFrame(query.all())
            
            if not df.empty:
                # Add formatted course-section identifier
                df['Course_Section'] = df.apply(
                    lambda row: f"{row['Course']}-{chr(ord('A') + row['SectionNumber'] - 1)}" 
                    if row['NumberOfSections'] > 1 else row['Course'], 
                    axis=1
                )
                
                # Add section type indicator
                df['Section_Type'] = df['NumberOfSections'].apply(
                    lambda x: 'Multi-Section' if x > 1 else 'Single-Section'
                )
            
            return df
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching section mapping dataframe: {e}")
            return pd.DataFrame()
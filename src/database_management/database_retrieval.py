import pandas as pd
from .dbconnection import get_db_session, is_postgresql, get_organization_database_url
from .models import User, Course, CourseStud, Slot, ProfessorBusySlot, CourseProfessor
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from sqlalchemy.orm import aliased
import logging

logger = logging.getLogger(__name__)

def registration_data(db_path):
    """
    Fetch registration data (student enrollments) using SQLAlchemy.
    Now handles multiple professors per course and PostgreSQL schema paths.
    
    :param db_path: Path to the database file or schema identifier
    :return: DataFrame containing registration data
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Create aliases for users table to distinguish between students and professors
            Student = aliased(User)
            Professor = aliased(User)
            
            # Query to get student registration data with joins
            # Use GROUP_CONCAT to combine multiple professors for a course
            # Use database-specific string aggregation function
            if is_postgresql():
                # PostgreSQL uses string_agg
                agg_func = func.string_agg(Professor.Email.distinct(), ', ')
            else:
                # SQLite uses group_concat
                agg_func = func.group_concat(Professor.Email.distinct())
            
            query = session.query(
                Student.Email.label('Roll No.'),
                Course.CourseName.label('G CODE'),
                agg_func.label('Professor'),
                Course.CourseType.label('Type'),
                Course.ClassesPerWeek.label('Classes Per Week')
            ).select_from(CourseStud)\
             .join(Student, CourseStud.StudentID == Student.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .join(CourseProfessor, Course.CourseID == CourseProfessor.CourseID)\
             .join(Professor, CourseProfessor.ProfessorID == Professor.UserID)\
             .filter(Student.Role == 'Student')\
             .filter(Professor.Role == 'Professor')\
             .group_by(Student.Email, Course.CourseName, Course.CourseType, Course.ClassesPerWeek)
            
            results = []
            for row in query.all():
                results.append({
                    'Roll No.': row._asdict()['Roll No.'],
                    'G CODE': row._asdict()['G CODE'],
                    'Professor': row._asdict()['Professor'],
                    'Type': row._asdict()['Type'],
                    'Classes Per Week': row._asdict()['Classes Per Week']
                })
            
            return pd.DataFrame(results)
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching registration data: {e}")
            return pd.DataFrame()

def registration_data_with_sections(db_path):
    """
    Fetch registration data with section information for section-aware timetable generation.
    
    :param db_path: Path to the database file or schema identifier
    :return: DataFrame containing registration data with section information
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get student registration data with section information
            query = session.query(
                User.Email.label('Roll No.'),
                Course.CourseName.label('BaseCourse'),
                CourseStud.SectionNumber,
                Course.CourseType.label('Type'),
                Course.ClassesPerWeek.label('Classes Per Week'),
                Course.NumberOfSections
            ).select_from(CourseStud)\
             .join(User, CourseStud.StudentID == User.UserID)\
             .join(Course, CourseStud.CourseID == Course.CourseID)\
             .filter(User.Role == 'Student')\
             .order_by(User.Email, Course.CourseName, CourseStud.SectionNumber)
            
            results = []
            for row in query.all():
                # Create course identifier based on number of sections
                base_course = row.BaseCourse
                section_num = row.SectionNumber
                num_sections = row.NumberOfSections
                
                if num_sections == 1:
                    # Single section: just use course name
                    course_identifier = base_course
                else:
                    # Multiple sections: use course-A, course-B format
                    section_letter = chr(ord('A') + section_num - 1)  # Convert 1->A, 2->B, etc.
                    course_identifier = f"{base_course}-{section_letter}"
                
                # Get professor for this specific section
                section_prof = get_professor_for_section(session, base_course, section_num)
                
                results.append({
                    'Roll No.': row._asdict()['Roll No.'],
                    'G CODE': course_identifier,
                    'BaseCourse': base_course,
                    'SectionNumber': section_num,
                    'Professor': section_prof,
                    'Type': row._asdict()['Type'],
                    'Classes Per Week': row._asdict()['Classes Per Week'],
                    'NumberOfSections': num_sections
                })
            
            return pd.DataFrame(results)
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching registration data with sections: {e}")
            return pd.DataFrame()

def get_professor_for_section(session, course_name, section_number):
    """
    Get the professor assigned to a specific section of a course using round-robin logic.
    
    :param session: Database session
    :param course_name: Name of the course
    :param section_number: Section number
    :return: Professor email or None
    """
    try:
        # Get all professors for this course from CourseProfessor table
        query = session.query(User.Email)\
                      .join(CourseProfessor, User.UserID == CourseProfessor.ProfessorID)\
                      .join(Course, CourseProfessor.CourseID == Course.CourseID)\
                      .filter(Course.CourseName == course_name)\
                      .filter(User.Role == 'Professor')\
                      .order_by(User.Email)  # Ensure consistent ordering
        
        professors = [prof.Email for prof in query.all()]
        
        if not professors:
            return None
        
        # Use round-robin assignment: section 1 -> prof 0, section 2 -> prof 1, etc.
        prof_index = (section_number - 1) % len(professors)
        return professors[prof_index]
        
    except Exception as e:
        logger.error(f"Error getting professor for section {section_number} of {course_name}: {e}")
        return None

def faculty_pref(db_path):
    """
    Fetch professor preferences for busy slots using SQLAlchemy.

    :param db_path: Path to the database file or schema identifier
    :return: DataFrame containing professor names and their busy time slots.
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get professor busy slots
            query = session.query(
                User.Email.label('Name'),
                (Slot.Day + ' ' + Slot.StartTime).label('Busy Slot')
            ).select_from(User)\
             .join(ProfessorBusySlot, User.UserID == ProfessorBusySlot.ProfessorID)\
             .join(Slot, ProfessorBusySlot.SlotID == Slot.SlotID)\
             .filter(User.Role == 'Professor')\
             .order_by(User.Email, Slot.Day, Slot.StartTime)
            
            results = []
            for row in query.all():
                results.append({
                    'Name': row.Name,
                    'Busy Slot': row._asdict()['Busy Slot']
                })
            
            return pd.DataFrame(results)
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching faculty preferences: {e}")
            return pd.DataFrame()

def student_pref(db_path):
    """
    Fetch student preferences for busy slots using SQLAlchemy.
    Note: This function seems to have an incorrect query in the original.
    Students don't have a CourseID field directly.

    :param db_path: Path to the database file or schema identifier
    :return: DataFrame containing student names and their busy time slots.
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get all students (the original query had an error)
            query = session.query(User.Email.label('Name'))\
                          .filter(User.Role == 'Student')\
                          .order_by(User.Email)
            
            results = []
            for row in query.all():
                results.append({
                    'Name': row.Name,
                    'Busy Slot': None  # No busy slot information available for students
                })
            
            return pd.DataFrame(results)
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching student preferences: {e}")
            return pd.DataFrame()

def get_all_time_slots(db_path):
    """
    Fetch all time slots from the database using SQLAlchemy.

    :param db_path: Path to the database file or schema identifier
    :return: List of time slot strings in "Day StartTime" format.
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get all time slots
            query = session.query(Slot).order_by(Slot.Day, Slot.StartTime)
            
            time_slots = []
            for slot in query.all():
                time_slot_str = f"{slot.Day} {slot.StartTime}"
                time_slots.append(time_slot_str)
            
            return time_slots
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching time slots: {e}")
            return []

def get_course_professor_mapping(db_path):
    """
    Create a mapping from course to professor using SQLAlchemy.

    :param db_path: Path to the database file or schema identifier
    :return: Dictionary mapping course codes to professor emails
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get course-professor mappings
            query = session.query(
                Course.CourseName,
                User.Email.label('ProfessorEmail'),
                CourseProfessor.SectionNumber
            ).select_from(Course)\
             .join(CourseProfessor, Course.CourseID == CourseProfessor.CourseID)\
             .join(User, CourseProfessor.ProfessorID == User.UserID)\
             .filter(User.Role == 'Professor')\
             .order_by(Course.CourseName, CourseProfessor.SectionNumber, User.Email)
            
            course_prof_map = {}
            for row in query.all():
                course_name = row.CourseName
                prof_email = row.ProfessorEmail
                section_number = row.SectionNumber
                
                # For multiple professors, use the first one (backward compatibility)
                if course_name not in course_prof_map:
                    course_prof_map[course_name] = prof_email
            
            return course_prof_map
            
        except SQLAlchemyError as e:
            logger.error(f"Error creating course-professor mapping: {e}")
            return {}

def get_course_section_professor_mapping(db_path):
    """
    Create a mapping from course-section identifier to professor for section-aware scheduling.
    
    :param db_path: Path to the database file or schema identifier
    :return: Dictionary mapping course-section identifiers to professor emails
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Query to get course information with section details directly from database
            query = session.query(
                Course.CourseName,
                Course.NumberOfSections,
                User.Email.label('ProfessorEmail'),
                CourseProfessor.SectionNumber
            ).select_from(Course)\
             .join(CourseProfessor, Course.CourseID == CourseProfessor.CourseID)\
             .join(User, CourseProfessor.ProfessorID == User.UserID)\
             .filter(User.Role == 'Professor')\
             .order_by(Course.CourseName, CourseProfessor.SectionNumber, User.Email)
            
            course_section_prof_map = {}
            
            # Directly map sections to professors from database
            for row in query.all():
                course_name = row.CourseName
                prof_email = row.ProfessorEmail
                num_sections = row.NumberOfSections
                section_number = row.SectionNumber
                
                # Create course-section identifier
                if num_sections == 1:
                    # Single section: just use course name
                    course_section_id = course_name
                else:
                    # Multiple sections: use course-A, course-B format
                    section_letter = chr(ord('A') + section_number - 1)  # Convert 1->A, 2->B, etc.
                    course_section_id = f"{course_name}-{section_letter}"
                
                course_section_prof_map[course_section_id] = prof_email
            
            return course_section_prof_map
            
        except SQLAlchemyError as e:
            logger.error(f"Error creating course-section-professor mapping: {e}")
            return {}

def create_course_classes_per_week_map(df):
    """
    Create a mapping from course to classes per week.
    
    :param df: DataFrame with 'G CODE' and 'Classes Per Week' columns
    :return: Dictionary mapping course codes to classes per week
    """
    course_classes_per_week_map = {}
    
    for index, row in df.iterrows():
        course_code = row['G CODE']
        classes_per_week = row['Classes Per Week']
        course_classes_per_week_map[course_code] = classes_per_week
    
    return course_classes_per_week_map

def create_course_elective_map(df):
    """
    Create a mapping from course to course type (Elective/Required).
    
    :param df: DataFrame with 'G CODE' and 'Type' columns
    :return: Dictionary mapping course codes to course types
    """
    course_type_map = {}
    
    for index, row in df.iterrows():
        course_code = row['G CODE']
        course_type = row['Type']
        course_type_map[course_code] = course_type
    
    return course_type_map
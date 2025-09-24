from .dbconnection import get_db_session, create_tables
from .models import User, Course, CourseProfessor
from .migration import migrate_database_for_sections, check_migration_needed, migrate_column_rename_credits_to_classes_per_week, check_credits_column_migration_needed
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def map_course_type(course_type):
    """
    Maps the course type to either 'Elective' or 'Required'.

    :param course_type: The original course type value.
    :return: 'Elective' if 'Elective' is in the value, else 'Required'.
    """
    if 'Elective' in course_type:
        return 'Elective'
    else:
        return 'Required'


def parse_faculty_names(faculty_name_str):
    """
    Parse faculty names separated by commas, ampersands, or both and return a list of cleaned names.
    
    :param faculty_name_str: String containing one or more faculty names separated by commas, ampersands, or both
    :return: List of faculty names
    """
    if pd.isna(faculty_name_str):
        return []
    
    # Handle both comma and ampersand separators
    faculty_str = str(faculty_name_str)
    
    # First split by commas, then by ampersands
    names = []
    for part in faculty_str.split(','):
        for name in part.split('&'):
            cleaned_name = name.strip()
            if cleaned_name:  # Remove empty strings
                names.append(cleaned_name)
    
    return names


def ensure_database_schema_is_current(db_path):
    """
    Ensure the database schema is up to date before performing operations.
    This function checks for common schema issues and runs migrations if needed.
    
    :param db_path: Path to the database file or schema identifier
    """
    from .dbconnection import is_postgresql, get_organization_database_url
    
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

    try:
        with session_context as session:
            # Check if Courses table exists and has the correct schema
            try:
                if is_postgresql():
                    schema = f'org_{org_name}' if org_name else 'public'
                    result = session.execute(text("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'Courses' AND table_schema = :schema
                        ORDER BY ordinal_position
                    """), {'schema': schema}).fetchall()
                    columns = [row[0] for row in result]
                else:
                    result = session.execute(text('PRAGMA table_info(Courses)')).fetchall()
                    columns = [row[1] for row in result]  # column names
                
                if columns:
                    has_credits = 'Credits' in columns
                    has_classes_per_week = 'ClassesPerWeek' in columns
                    
                    logger.info(f"Courses table schema check - Credits: {has_credits}, ClassesPerWeek: {has_classes_per_week}")
                    
                    if has_credits and not has_classes_per_week:
                        logger.info("Detected old schema with Credits column, running migration...")
                        print("🔄 Updating database schema: Credits → ClassesPerWeek")
                        migrate_column_rename_credits_to_classes_per_week(db_path)
                        logger.info("Schema migration completed successfully")
                        print("✅ Database schema updated successfully")
                    elif has_classes_per_week:
                        logger.info("Database schema is current (ClassesPerWeek column exists)")
                    else:
                        logger.info("Fresh database installation detected")
                else:
                    logger.info("Courses table does not exist yet, will be created")
                    
            except Exception as e:
                logger.debug(f"Could not check Courses table schema: {e}")
                # Table might not exist yet, which is fine
                
    except Exception as e:
        logger.warning(f"Could not perform schema check: {e}")
        # Continue anyway, the error handling in insert will catch any issues


def insert_courses_professors(file, db_path):
    """
    Inserts course information with section support using bulk operations.
    Handles multiple professors per course and creates sections accordingly.
    Keeps complex course patterns intact (e.g., "HIST330|SOCL330|POLT330").

    :param file: The CSV file containing courses and faculty names.
    :param db_path: Path to the database file or schema identifier.
    """
    print("BULK INSERTING COURSES")
    df_courses = file

    from .dbconnection import is_postgresql, get_organization_database_url
    
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # Ensure database schema is current before proceeding
    ensure_database_schema_is_current(db_path)

    # Check if migration is needed and run it (only for SQLite)
    if not is_postgresql() and check_migration_needed(db_path):
        print("Database migration needed for sections support...")
        migrate_database_for_sections(db_path)
        print("Database migration completed.")
    
    # Check if Credits column migration is needed
    if check_credits_column_migration_needed(db_path):
        print("Database migration needed for Credits -> ClassesPerWeek column rename...")
        migrate_column_rename_credits_to_classes_per_week(db_path)
        print("Credits column migration completed.")

    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Courses table exists by querying it
                session.execute(text("SELECT 1 FROM \"Courses\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Courses table exists by querying it
                session.execute(text("SELECT 1 FROM Courses LIMIT 1"))
    except Exception as e:
        # If table doesn't exist, create all tables
        logger.info(f"Courses table not found, creating tables... Error: {e}")
        if is_postgresql() and org_name:
            create_tables(get_organization_database_url(), org_name)
        else:
            create_tables(db_path)
        logger.info("Tables created successfully")
        
        # After creating tables, re-run schema check to ensure everything is consistent
        logger.info("Re-running schema check after table creation...")
        ensure_database_schema_is_current(db_path)

    # Determine which session to use
    if is_postgresql() and org_name:
        session_context = get_db_session(get_organization_database_url(), org_name)
    else:
        session_context = get_db_session(db_path)

    with session_context as session:
        try:
            # Fetch user information (UserID and Email) for professors
            professors = session.query(User).filter_by(Role='Professor').all()
            prof_dict = {prof.Email: prof.UserID for prof in professors}
            
            print(f"Found {len(prof_dict)} professors in database: {list(prof_dict.keys())}")

            # Prepare data for bulk insert
            courses_to_insert = []
            course_professor_relationships = []
            processed_courses = set()  # Track unique courses

            # Process each course pattern - keep complex patterns intact
            for index, row in df_courses.iterrows():
                try:
                    course_code = row['Course code']  # Keep complex patterns like "HIST330|SOCL330|POLT330"
                    faculty_names_str = row['Faculty Name']
                    course_type = map_course_type(row['Type'])
                    classes_per_week = row['Classes Per Week']  # Changed from Credits to Classes Per Week
                    
                    # Get number of sections (default to 1 if not provided)
                    num_sections = row.get('Number of Sections', 1)
                    if pd.isna(num_sections):
                        num_sections = 1
                    num_sections = int(num_sections)

                    # Parse faculty names (handles both comma and ampersand separators)
                    faculty_names = parse_faculty_names(faculty_names_str)
                    
                    if not faculty_names:
                        logger.warning(f"No valid faculty names found for course {course_code}")
                        continue

                    print(f"Course pattern: {course_code} -> Faculty: {faculty_names} -> Sections: {num_sections}")

                    # Add course pattern to bulk insert list (avoid duplicates)
                    if course_code not in processed_courses:
                        courses_to_insert.append({
                            'CourseName': course_code,  # Keep complex pattern as-is
                            'CourseType': course_type,
                            'ClassesPerWeek': classes_per_week,
                            'NumberOfSections': num_sections
                        })
                        processed_courses.add(course_code)

                    # Prepare course-professor relationships with section assignments
                    # Check if this is team teaching (multiple professors for same course)
                    # vs distributed teaching (different professors for different sections)
                    
                    if len(faculty_names) > 1 and num_sections > 1:
                        # OPTION 1: Team teaching - all professors teach all sections together
                        # This is the case for courses like "Prof A & Prof B & Prof C"
                        for section_num in range(1, num_sections + 1):
                            for assigned_professor in faculty_names:
                                professor_id = prof_dict.get(assigned_professor)
                                if professor_id:
                                    course_professor_relationships.append({
                                        'CourseName': course_code,
                                        'ProfessorID': professor_id,
                                        'FacultyName': assigned_professor,
                                        'SectionNumber': section_num
                                    })
                                    logger.info(f"[TEAM TEACHING] Will link professor {assigned_professor} to course {course_code} section {section_num}")
                                else:
                                    logger.warning(f"Professor '{assigned_professor}' not found for course {course_code}")
                    else:
                        # OPTION 2: Single professor or round-robin assignment for multiple sections
                        for section_num in range(1, num_sections + 1):
                            if len(faculty_names) == 1:
                                # Single professor teaches all sections
                                assigned_professor = faculty_names[0]
                            else:
                                # Round-robin assignment for multiple professors
                                prof_index = (section_num - 1) % len(faculty_names)
                                assigned_professor = faculty_names[prof_index]
                            
                            professor_id = prof_dict.get(assigned_professor)
                            if professor_id:
                                course_professor_relationships.append({
                                    'CourseName': course_code,
                                    'ProfessorID': professor_id,
                                    'FacultyName': assigned_professor,
                                    'SectionNumber': section_num
                                })
                                logger.info(f"[DISTRIBUTED] Will link professor {assigned_professor} to course {course_code} section {section_num}")
                            else:
                                logger.warning(f"Professor '{assigned_professor}' not found for course {course_code}")

                except Exception as e:
                    logger.error(f"Error processing course {row.get('Course code', 'Unknown')}: {e}")

            # Bulk insert courses
            if courses_to_insert:
                # Check for existing courses and filter them out
                existing_courses = {course.CourseName for course in session.query(Course.CourseName).all()}
                new_courses = [course for course in courses_to_insert if course['CourseName'] not in existing_courses]
                
                if new_courses:
                    try:
                        session.bulk_insert_mappings(Course, new_courses)
                        session.commit()
                        logger.info(f"Bulk inserted {len(new_courses)} courses")
                        print(f"Bulk inserted {len(new_courses)} courses (keeping complex patterns intact)")
                    except Exception as e:
                        # Check if this is a column name issue (Credits vs ClassesPerWeek)
                        error_str = str(e).lower()
                        if 'classesperweek' in error_str and ('does not exist' in error_str or 'column' in error_str):
                            logger.warning("ClassesPerWeek column not found, attempting migration...")
                            print("Detected old database schema, running migration...")
                            
                            # Run the migration
                            session.rollback()
                            migrate_column_rename_credits_to_classes_per_week(db_path)
                            
                            # Retry the insert after migration
                            try:
                                session.bulk_insert_mappings(Course, new_courses)
                                session.commit()
                                logger.info(f"Bulk inserted {len(new_courses)} courses after migration")
                                print(f"✅ Successfully inserted {len(new_courses)} courses after migration")
                            except Exception as e2:
                                logger.error(f"Failed to insert courses even after migration: {e2}")
                                raise
                        else:
                            # Re-raise original error if it's not related to column names
                            raise
                else:
                    logger.info("No new courses to insert")
                    print("No new courses to insert (all already exist)")

            # Now get course IDs for the relationships
            courses = session.query(Course).all()
            course_id_map = {course.CourseName: course.CourseID for course in courses}

            # Prepare and bulk insert course-professor relationships
            if course_professor_relationships:
                relationships_to_insert = []
                for rel in course_professor_relationships:
                    course_id = course_id_map.get(rel['CourseName'])
                    if course_id:
                        relationships_to_insert.append({
                            'CourseID': course_id,
                            'ProfessorID': rel['ProfessorID'],
                            'SectionNumber': rel['SectionNumber']
                        })

                # Check for existing relationships and filter them out
                existing_relations = set()
                for rel in session.query(CourseProfessor).all():
                    existing_relations.add((rel.CourseID, rel.ProfessorID, rel.SectionNumber))

                # Filter out existing relationships and also deduplicate within new relationships
                seen_relationships = set()
                new_relationships = []
                for rel in relationships_to_insert:
                    key = (rel['CourseID'], rel['ProfessorID'], rel['SectionNumber'])
                    if key not in existing_relations and key not in seen_relationships:
                        new_relationships.append(rel)
                        seen_relationships.add(key)

                if new_relationships:
                    session.bulk_insert_mappings(CourseProfessor, new_relationships)
                    session.commit()
                    logger.info(f"Bulk inserted {len(new_relationships)} course-professor relationships")
                    print(f"Bulk inserted {len(new_relationships)} course-professor relationships")
                else:
                    logger.info("No new course-professor relationships to insert")

        except Exception as e:
            session.rollback()
            logger.error(f"Error bulk inserting course data: {e}")
            raise


def fetch_course_data(db_path):
    """
    Fetches all course data from the Courses table using SQLAlchemy.
    Now returns courses with their associated professors.

    :param db_path: Path to the database file or schema identifier.
    :return: List of all course data with professor information.
    """
    from .dbconnection import is_postgresql, get_organization_database_url
    
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
            # Query courses with their professors
            query = session.query(
                Course.CourseID,
                Course.CourseName,
                Course.CourseType,
                Course.ClassesPerWeek,
                User.Email.label('ProfessorEmail'),
                User.Name.label('ProfessorName')
            ).select_from(Course)\
             .join(CourseProfessor, Course.CourseID == CourseProfessor.CourseID)\
             .join(User, CourseProfessor.ProfessorID == User.UserID)\
             .order_by(Course.CourseName, User.Email)
            
            result = []
            for row in query.all():
                result.append((
                    row.CourseID,
                    row.CourseName,
                    row.ProfessorEmail,
                    row.CourseType,
                    row.ClassesPerWeek,
                    row.ProfessorName
                ))
            
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error fetching course data: {e}")
            return []


def get_professors_for_course(course_name, db_path):
    """
    Get all professors assigned to a specific course.
    
    :param course_name: Name of the course
    :param db_path: Path to the database file
    :return: List of professor emails
    """
    with get_db_session(db_path) as session:
        try:
            query = session.query(User.Email)\
                          .join(CourseProfessor, User.UserID == CourseProfessor.ProfessorID)\
                          .join(Course, CourseProfessor.CourseID == Course.CourseID)\
                          .filter(Course.CourseName == course_name)
            
            professors = [prof.Email for prof in query.all()]
            return professors
        except SQLAlchemyError as e:
            logger.error(f"Error fetching professors for course {course_name}: {e}")
            return []
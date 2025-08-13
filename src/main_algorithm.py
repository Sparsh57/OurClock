from .data_preprocessing import merge_data, prepare_student_course_map, create_course_professor_map_all, prepare_student_course_section_map, expand_courses_with_sections
from .utilities import faculty_busy_slots, create_course_dictionary
from .schedule_model import schedule_courses
from .database_management.schedule import schedule
from .database_management.Courses import fetch_course_data
from .conflict_checker import check_conflicts, find_courses_with_multiple_slots_on_same_day
from .database_management.database_retrieval import registration_data, faculty_pref, get_all_time_slots, registration_data_with_sections, get_course_section_professor_mapping, create_course_classes_per_week_map, create_course_elective_map
from .database_management.migration import migrate_database_for_sections, check_migration_needed
from .database_management.Slot_info import ensure_default_time_slots
from .database_management.settings_manager import get_max_classes_per_slot, initialize_default_settings
import pandas as pd
import random


def gen_student_csv(student_list, course_list):
    data = []
    for student in student_list:
        courses = random.sample(course_list, 5)
        for i in courses:
            data.append({"Roll No.": student, "G CODE": i, "Sections": "A"})
    df = pd.DataFrame(data)
    df.to_csv("Student Registration Data.csv", index=False)

def diagnose_same_day_constraints(courses, course_classes_per_week):
    """
    Prints a diagnostic for each course that has fewer unique days than
    required classes per week. If a course needs 'X' sessions (classes per week = X) but
    only has Y < X distinct days, you'll never be able to schedule them
    all on different days.
    """
    for course_id, info in courses.items():
        # Extract days from each time slot
        slot_days = set()
        for slot in info["time_slots"]:
            day = slot.split()[0]  # or your get_day_from_time_slot(slot)
            slot_days.add(day)

        needed = course_classes_per_week.get(course_id, 2)  # default if missing
        day_count = len(slot_days)

        if day_count < needed:
            print(f"[DIAGNOSTIC] Course '{course_id}' needs {needed} sessions, "
                  f"but only has {day_count} unique day(s): {sorted(slot_days)}")
    print("[DIAGNOSTIC] Done checking same-day constraints.")

def gen_timetable(db_path, max_classes_per_slot=24, 
                   add_prof_constraints=True, add_timeslot_capacity=True, 
                   add_student_conflicts=True, add_no_same_day=True, 
                   add_no_consec_days=False):
    """
    Generate timetable using the original algorithm (backward compatibility).
    
    :param db_path: Path to the database file
    :param max_classes_per_slot: Maximum number of classes allowed per time slot
    :param add_prof_constraints: Whether to add professor conflict constraints
    :param add_timeslot_capacity: Whether to enforce time slot capacity limits
    :param add_student_conflicts: Whether to add student conflict constraints
    :param add_no_same_day: Whether to prevent same course multiple times per day
    :param add_no_consec_days: Whether to prevent courses on consecutive days
    """
    # Ensure default time slots exist
    ensure_default_time_slots(db_path)
    
    df_merged = registration_data(db_path)
    student_course_map = prepare_student_course_map(df_merged)
    course_professor_map = create_course_professor_map_all(df_merged)
    df_faculty_pref = faculty_pref(db_path)
    professor_busy_slots = faculty_busy_slots(df_faculty_pref)
    course_classes_per_week_map = create_course_classes_per_week_map(df_merged)
    course_type_map = create_course_elective_map(df_merged)
    time_slots = get_all_time_slots(db_path)
    # Preprocess courses and schedule
    courses = create_course_dictionary(student_course_map, course_professor_map, professor_busy_slots, time_slots)
    diagnose_same_day_constraints(courses, course_classes_per_week_map)
    schedule_data, infeasibility_reason = schedule_courses(courses, student_course_map, course_professor_map, course_classes_per_week_map, course_type_map, [], 
                                   add_prof_constraints, add_timeslot_capacity, add_student_conflicts, 
                                   add_no_same_day, add_no_consec_days, max_classes_per_slot)

    print("Schedule Data")
    print(schedule_data)
    print("Infeasibility Reason:", infeasibility_reason)
    
    # If the schedule is empty, return the infeasibility reason
    if schedule_data.empty:
        return schedule_data, pd.DataFrame(), infeasibility_reason
    
    print()
    print("Courses on the same day")
    print(find_courses_with_multiple_slots_on_same_day(schedule_data))
    print("Conflicts")
    conflicts = check_conflicts(schedule_data, student_course_map)
    print(conflicts)
    schedule(schedule_data, db_path)
    return schedule_data, conflicts, infeasibility_reason


def gen_timetable_with_sections(db_path, max_classes_per_slot=24,
                                 add_prof_constraints=True, add_timeslot_capacity=True, 
                                 add_student_conflicts=True, add_no_same_day=True, 
                                 add_no_consec_days=False):
    """
    Generate timetable with section support using the new section-aware algorithm.
    
    :param db_path: Path to the database file
    :param max_classes_per_slot: Maximum number of classes allowed per time slot
    :param add_prof_constraints: Whether to add professor conflict constraints
    :param add_timeslot_capacity: Whether to enforce time slot capacity limits
    :param add_student_conflicts: Whether to add student conflict constraints
    :param add_no_same_day: Whether to prevent same course multiple times per day
    :param add_no_consec_days: Whether to prevent courses on consecutive days
    """
    print("Generating timetable with section support...")
    
    # Get section-aware registration data
    df_merged = registration_data_with_sections(db_path)
    
    if df_merged.empty:
        print("No registration data found, falling back to original algorithm")
        return gen_timetable(db_path, max_classes_per_slot, add_prof_constraints, 
                           add_timeslot_capacity, add_student_conflicts, 
                           add_no_same_day, add_no_consec_days)
    
    print(f"Found {len(df_merged)} student-course-section enrollments")
    
    # Use section-specific course identifiers for mapping
    student_course_map = prepare_student_course_section_map(df_merged)
    
    # Get section-specific professor mapping
    course_professor_map = get_course_section_professor_mapping(db_path)
    
    # Convert to the format expected by the algorithm
    course_professor_map_all = {}
    for course_section_id, prof_email in course_professor_map.items():
        course_professor_map_all[course_section_id] = [prof_email]
    
    # Get other required data
    df_faculty_pref = faculty_pref(db_path)
    professor_busy_slots = faculty_busy_slots(df_faculty_pref)
    
    # Create classes per week and type maps based on base courses
    course_classes_per_week_map = {}
    course_type_map = {}
    for _, row in df_merged.iterrows():
        course_section_id = row['G CODE']
        course_classes_per_week_map[course_section_id] = row['Classes Per Week']
        course_type_map[course_section_id] = row['Type']
    
    # Ensure default time slots exist
    ensure_default_time_slots(db_path)
    
    time_slots = get_all_time_slots(db_path)
    
    # DEBUG: Print time slot information
    print(f"🕐 DEBUG: Found {len(time_slots)} time slots in database")
    if len(time_slots) == 0:
        error_msg = ("CRITICAL ERROR: No time slots found!\n\n"
                    "Cannot generate timetable without time slots.\n\n"
                    "Solutions:\n"
                    "• Add time slots via /select_timeslot\n"
                    "• Check if time slots were properly saved to database\n"
                    "• Verify database connection is working")
        print(f"❌ {error_msg}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), pd.DataFrame(), error_msg
    else:
        print(f"✅ Time slots available: {time_slots[:5]}..." if len(time_slots) > 5 else f"✅ Time slots available: {time_slots}")
    
    print(f"📊 Max classes per slot configured: {max_classes_per_slot}")
    
    # Preprocess courses and schedule (treating each section as a separate course)
    courses = create_course_dictionary(student_course_map, course_professor_map_all, professor_busy_slots, time_slots)
    
    print(f"Processing {len(courses)} course sections")
    
    # Diagnose constraints
    diagnose_same_day_constraints(courses, course_classes_per_week_map)
    
    # Generate schedule
    schedule_data, infeasibility_reason = schedule_courses(courses, student_course_map, course_professor_map_all, course_classes_per_week_map, course_type_map, [], 
                                   add_prof_constraints, add_timeslot_capacity, add_student_conflicts, 
                                   add_no_same_day, add_no_consec_days, max_classes_per_slot)

    print("Schedule Data (Section-aware)")
    print(schedule_data)
    print("Infeasibility Reason:", infeasibility_reason)
    
    # If the schedule is empty, return the infeasibility reason
    if schedule_data.empty:
        return schedule_data, pd.DataFrame(), infeasibility_reason
    
    print()
    print("Courses on the same day")
    print(find_courses_with_multiple_slots_on_same_day(schedule_data))
    print("Conflicts")
    conflicts = check_conflicts(schedule_data, student_course_map)
    print(conflicts)
    
    # Save schedule to database
    schedule(schedule_data, db_path)
    
    return schedule_data, conflicts, infeasibility_reason


def has_multi_section_courses(db_path):
    """
    Check if the database has any courses with multiple sections.
    
    :param db_path: Path to the database
    :return: True if multi-section courses exist, False otherwise
    """
    try:
        # Ensure migration is done before checking
        if check_migration_needed(db_path):
            migrate_database_for_sections(db_path)
        
        # First check if there are any multi-section courses in the Courses table
        from .database_management.section_allocation import get_multi_section_courses
        multi_section_courses = get_multi_section_courses(db_path)
        
        print(f"🔍 Multi-section courses found in database: {multi_section_courses}")
        
        if multi_section_courses:
            print(f"✅ Found {len(multi_section_courses)} multi-section courses")
            return True
        
        # Fallback to checking registration data
        df_merged = registration_data_with_sections(db_path)
        has_multi_sections = not df_merged.empty and df_merged['NumberOfSections'].max() > 1
        
        if has_multi_sections:
            print(f"✅ Multi-section courses detected in registration data")
        else:
            print(f"❌ No multi-section courses detected")
        
        return has_multi_sections
        
    except Exception as e:
        print(f"Error checking for multi-section courses: {e}")
        return False


def gen_timetable_auto(db_path, max_classes_per_slot=None, 
                       add_prof_constraints=True, add_timeslot_capacity=True, 
                       add_student_conflicts=True, add_no_same_day=True, 
                       add_no_consec_days=False):
    """
    Automatically choose between section-aware and original timetable generation
    based on whether multi-section courses exist.
    
    :param db_path: Path to the database
    :param max_classes_per_slot: Maximum number of classes per slot (if None, uses database setting)
    :param add_prof_constraints: Whether to add professor conflict constraints
    :param add_timeslot_capacity: Whether to enforce time slot capacity limits
    :param add_student_conflicts: Whether to add student conflict constraints
    :param add_no_same_day: Whether to prevent same course multiple times per day
    :param add_no_consec_days: Whether to prevent courses on consecutive days
    :return: Schedule data and conflicts
    """
    print(f"🚀 Starting auto timetable generation...")
    print(f"   📁 Database path: {db_path}")
    
    # Initialize default settings if they don't exist
    initialize_default_settings(db_path)
    
    # Get max classes per slot from database if not provided
    if max_classes_per_slot is None:
        max_classes_per_slot = get_max_classes_per_slot(db_path)
    
    print(f"📊 Using max classes per slot: {max_classes_per_slot}")
    
    # Ensure database is migrated for sections support
    if check_migration_needed(db_path):
        print("Database migration needed for sections support...")
        migrate_database_for_sections(db_path)
        print("Database migration completed.")
    
    print(f"🔍 Checking for multi-section courses...")
    if has_multi_section_courses(db_path):
        print("✅ Multi-section courses detected, using section-aware algorithm")
        return gen_timetable_with_sections(db_path, max_classes_per_slot, 
                                         add_prof_constraints, add_timeslot_capacity,
                                         add_student_conflicts, add_no_same_day, add_no_consec_days)
    else:
        print("❌ No multi-section courses detected, using original algorithm")
        return gen_timetable(db_path, max_classes_per_slot,
                           add_prof_constraints, add_timeslot_capacity,
                           add_student_conflicts, add_no_same_day, add_no_consec_days)
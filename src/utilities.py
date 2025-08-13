import pandas as pd


def faculty_busy_slots(df_faculty_pref):
    return df_faculty_pref.groupby("Name")["Busy Slot"].agg(list).to_dict()


def create_course_dictionary(student_course_map, course_professor_map, professor_busy_slots, time_slots):
    """
    Generates a dictionary with each course's available time slots.
    Now supports multiple professors per course.

    Args:
        student_course_map (dict): Mapping of student identifiers to lists of courses.
        course_professor_map (dict): Mapping of courses to their assigned professors (can be list or single professor).
        professor_busy_slots (dict): Mapping of professor identifiers to a list of busy time slots.
        time_slots (list): List of time slot strings (e.g., "Monday 08:30") to consider.

    Returns:
        dict: A dictionary where keys are course names and values are dictionaries with available 'time_slots'.
    """
    unique_courses = set().union(*student_course_map.values())
    course_availability = {}

    # You can also define excluded slots i f needed, or pass them as an extra parameter.
    excluded_slots = []
    for course in unique_courses:
        professors = course_professor_map.get(course, [])
        
        # Handle both single professor (string) and multiple professors (list) for backward compatibility
        if isinstance(professors, str):
            professors = [professors]
        elif professors is None:
            professors = []
        
        # Collect busy slots from ALL professors assigned to this course
        all_busy_slots = set()
        for professor in professors:
            busy_slots = professor_busy_slots.get(professor, [])
            all_busy_slots.update(busy_slots)
        
        # Filter the provided time_slots list based on ALL professors' busy slots and any exclusions.
        available_slots = [slot for slot in time_slots if slot not in all_busy_slots and slot not in excluded_slots]
        course_availability[course] = {'time_slots': available_slots}

    return course_availability

def create_course_classes_per_week_map(df_courses):
    try:
        # More efficient way to convert to numeric, handling errors and NaNs
        df_courses['Classes Per Week'] = pd.to_numeric(df_courses['Classes Per Week'], errors='coerce').fillna(2).astype(int)
    except (KeyError, TypeError):  # Handle missing or incorrect column names
        return {}  # or raise error as you see fit

    return df_courses.set_index('G CODE')['Classes Per Week'].to_dict()


def create_course_elective_map(df_courses):
    return pd.Series(df_courses['Type'].values, index=df_courses['G CODE']).to_dict()

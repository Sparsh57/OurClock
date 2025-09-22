from ortools.sat.python import cp_model
import pandas as pd
from typing import Dict, List, Union
from collections import defaultdict


def get_day_from_time_slot(time_slot: str) -> str:
    """
    Example: "Monday 9am-10am" -> "Monday"
    Adjust if your actual string format is different.
"""
    return time_slot.split()[0]


def diagnose_phase1_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_classes_per_week: Dict[str, int]) -> str:
    """
    Diagnose Phase 1 failures: Basic classes per week constraints
    """
    diagnosis_lines = [
        "PHASE 1 FAILED: Basic 'classes per week' constraints cannot be satisfied",
        "",
        "DETAILED ANALYSIS:",
        "=" * 50
    ]
    
    problem_courses = []
    
    for course_id, classes_needed in course_classes_per_week.items():
        if course_id not in courses:
            problem_courses.append({
                'course': course_id,
                'needed': classes_needed,
                'available': 0,
                'issue': 'Course not found in availability data'
            })
            continue
        
        # Get maximum available slots across all professors for this course
        max_available = 0
        course_data = courses[course_id]
        
        for professor, slots in course_data.items():
            max_available = max(max_available, len(slots))
        
        if classes_needed > max_available:
            problem_courses.append({
                'course': course_id,
                'needed': classes_needed,
                'available': max_available,
                'issue': 'Insufficient time slots'
            })
    
    if problem_courses:
        diagnosis_lines.append("PROBLEM COURSES:")
        diagnosis_lines.append("-" * 20)
        
        for course_info in problem_courses:
            diagnosis_lines.extend([
                f"Course: {course_info['course']}",
                f"  Classes needed per week: {course_info['needed']}",
                f"  Maximum available slots: {course_info['available']}",
                f"  Issue: {course_info['issue']}",
                ""
            ])
        
        diagnosis_lines.extend([
            "RECOMMENDED SOLUTIONS:",
            "1. Add more time slots to the weekly schedule",
            "2. Reduce classes per week for problematic courses",
            "3. Check professor busy slots - may be too restrictive",
            "4. Verify course requirements are realistic for available time"
        ])
    else:
        diagnosis_lines.append("No obvious course-level issues found. This may be a complex constraint interaction.")
    
    return "\n".join(diagnosis_lines)


def diagnose_phase2_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_professor_map: Dict[str, Union[str, List[str]]],
                             course_classes_per_week: Dict[str, int]) -> str:
    """
    Diagnose specific professor conflicts that cause Phase 2 failures
    """
    # Build professor -> courses mapping
    prof_dict = defaultdict(list)
    for c_id, profs in course_professor_map.items():
        if isinstance(profs, str):
            profs = [profs]
        elif profs is None:
            profs = []
        
        for prof in profs:
            prof_dict[prof].append(c_id)
    
    diagnosis_lines = [
        "PHASE 2 FAILED: Professor scheduling conflicts detected",
        "",
        "DETAILED CONFLICT ANALYSIS:",
        "=" * 50
    ]
    
    # Track critical issues
    critical_professors = []
    
    for professor, course_list in prof_dict.items():
        if not course_list:
            continue
            
        # Count total classes needed for this professor
        total_classes_needed = sum(course_classes_per_week.get(c_id, 0) for c_id in course_list)
        
        # Count available slots for this professor
        available_slots = 0
        prof_courses = courses.get(course_list[0], {}) if course_list else {}
        if professor in prof_courses:
            available_slots = len(prof_courses[professor])
        else:
            # Check all courses to find the professor's availability
            for c_id in course_list:
                if c_id in courses and professor in courses[c_id]:
                    available_slots = len(courses[c_id][professor])
                    break
        
        # Determine conflict severity
        conflict_type = "OK"
        if total_classes_needed > available_slots:
            conflict_type = "CRITICAL"
            critical_professors.append(professor)
        elif total_classes_needed == available_slots:
            conflict_type = "WARNING"
        
        diagnosis_lines.extend([
            f"Professor: {professor}",
            f"  Assigned Courses: {', '.join(course_list)}",
            f"  Total Classes Needed: {total_classes_needed}",
            f"  Available Time Slots: {available_slots}",
            f"  Status: {conflict_type}",
            ""
        ])
    
    # Add summary and recommendations
    if critical_professors:
        diagnosis_lines.extend([
            "CRITICAL ISSUES FOUND:",
            "-" * 25
        ])
        for prof in critical_professors:
            diagnosis_lines.append(f"Redistribute courses from: {prof}")
        
        diagnosis_lines.extend([
            "",
            "RECOMMENDED ACTIONS:",
            "1. Remove busy slots for overloaded professors",
            "2. Reassign some courses to other professors", 
            "3. Add more time slots to the schedule",
            "4. Reduce classes per week for some courses"
        ])
    
    # Check for courses without professors
    unassigned_courses = []
    for c_id, profs in course_professor_map.items():
        if not profs or (isinstance(profs, list) and not profs):
            unassigned_courses.append(c_id)
    
    if unassigned_courses:
        diagnosis_lines.extend([
            "",
            "COURSES WITHOUT ASSIGNED PROFESSORS:",
            "-" * 35
        ])
        diagnosis_lines.extend(unassigned_courses)
        diagnosis_lines.extend([
            "",
            "Action Required: Assign professors to these courses"
        ])
    
    return "\n".join(diagnosis_lines)


def diagnose_phase3_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_classes_per_week: Dict[str, int],
                             max_classes_per_slot: int) -> str:
    """
    Diagnose Phase 3 failures: Time slot capacity constraints
    """
    diagnosis_lines = [
        "PHASE 3 FAILED: Time slot capacity limit exceeded",
        "",
        "DETAILED CAPACITY ANALYSIS:",
        "=" * 50
    ]
    
    # Count total classes needed
    total_classes = sum(course_classes_per_week.values())
    
    # Count available time slots (unique across all courses)
    all_time_slots = set()
    for course_data in courses.values():
        for prof_slots in course_data.values():
            all_time_slots.update(prof_slots)
    
    total_capacity = len(all_time_slots) * max_classes_per_slot
    
    diagnosis_lines.extend([
        f"Total classes needed: {total_classes}",
        f"Available time slots: {len(all_time_slots)}",
        f"Max classes per slot: {max_classes_per_slot}",
        f"Total capacity: {total_capacity}",
        f"Capacity deficit: {total_classes - total_capacity}",
        "",
        "COURSES REQUIRING CLASSES:",
        "-" * 30
    ])
    
    # Show breakdown by course
    for course_id, classes in course_classes_per_week.items():
        diagnosis_lines.append(f"{course_id}: {classes} classes")
    
    diagnosis_lines.extend([
        "",
        "RECOMMENDED SOLUTIONS:",
        f"1. Increase max classes per slot from {max_classes_per_slot}",
        "2. Add more time slots to the schedule",
        "3. Reduce classes per week for some courses",
        "4. Split large courses into multiple sections"
    ])
    
    return "\n".join(diagnosis_lines)


def diagnose_phase4_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_professor_map: Dict[str, Union[str, List[str]]]) -> str:
    """
    Diagnose Phase 4 failures: Student conflict constraints (rare)
    """
    diagnosis_lines = [
        "PHASE 4 FAILED: Student conflict constraints causing infeasibility",
        "",
        "ANALYSIS:",
        "=" * 50,
        "",
        "This is unusual since student conflict constraints are designed to be soft/flexible.",
        "The failure suggests a deeper scheduling problem or unusual enrollment patterns.",
        "",
        "POSSIBLE CAUSES:",
        "- Very high course overlap in student enrollments",
        "- Limited time slot availability after professor constraints", 
        "- Complex interaction between multiple constraint types",
        "",
        "COURSE-PROFESSOR ASSIGNMENTS:",
        "-" * 35
    ]
    
    for course_id, profs in course_professor_map.items():
        if isinstance(profs, str):
            prof_list = [profs]
        elif isinstance(profs, list):
            prof_list = profs
        else:
            prof_list = ["No professor assigned"]
        
        diagnosis_lines.append(f"{course_id}: {', '.join(prof_list)}")
    
    diagnosis_lines.extend([
        "",
        "RECOMMENDED ACTIONS:",
        "1. Review student enrollment patterns for unusual overlaps",
        "2. Try disabling some constraint options temporarily",
        "3. Check if professor availability is too restrictive",
        "4. Consider splitting high-enrollment courses",
        "5. Contact system administrator for advanced troubleshooting"
    ])
    
    return "\n".join(diagnosis_lines)


def diagnose_phase5_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_classes_per_week: Dict[str, int]) -> str:
    """
    Diagnose Phase 5 failures: No same course twice on same day
    """
    diagnosis_lines = [
        "PHASE 5 FAILED: 'No same course twice on the same day' constraint",
        "",
        "ANALYSIS:",
        "=" * 50
    ]
    
    # Analyze courses that need multiple classes
    multi_class_courses = [(cid, classes) for cid, classes in course_classes_per_week.items() if classes > 1]
    
    if multi_class_courses:
        diagnosis_lines.extend([
            "COURSES NEEDING MULTIPLE CLASSES PER WEEK:",
            "-" * 45
        ])
        
        for course_id, classes in multi_class_courses:
            # Count available days for this course
            available_days = set()
            if course_id in courses:
                for prof_slots in courses[course_id].values():
                    for slot in prof_slots:
                        day = get_day_from_time_slot(slot)
                        available_days.add(day)
            
            status = "OK" if classes <= len(available_days) else "PROBLEM"
            
            diagnosis_lines.extend([
                f"Course: {course_id}",
                f"  Classes needed: {classes}",
                f"  Available days: {len(available_days)} ({', '.join(sorted(available_days))})",
                f"  Status: {status}",
                ""
            ])
    
    diagnosis_lines.extend([
        "RECOMMENDED SOLUTIONS:",
        "1. Add time slots on different days of the week",
        "2. Review professor busy slots - some may block entire days",
        "3. Reduce classes per week for problematic courses",
        "4. Consider disabling the 'same day' constraint if flexible scheduling is acceptable"
    ])
    
    return "\n".join(diagnosis_lines)


def diagnose_phase6_conflicts(courses: Dict[str, Dict[str, List[str]]],
                             course_classes_per_week: Dict[str, int]) -> str:
    """
    Diagnose Phase 6 failures: No consecutive days constraint
    """
    diagnosis_lines = [
        "PHASE 6 FAILED: 'No consecutive days' constraint",
        "",
        "ANALYSIS:",
        "=" * 50
    ]
    
    # Analyze day distribution
    all_available_days = set()
    for course_data in courses.values():
        for prof_slots in course_data.values():
            for slot in prof_slots:
                day = get_day_from_time_slot(slot)
                all_available_days.add(day)
    
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    available_ordered_days = [day for day in day_order if day in all_available_days]
    
    diagnosis_lines.extend([
        f"Available days in schedule: {', '.join(available_ordered_days)}",
        f"Total courses needing multiple classes: {sum(1 for c in course_classes_per_week.values() if c > 1)}",
        "",
        "CONSECUTIVE DAY ANALYSIS:",
        "-" * 30
    ])
    
    # Check for consecutive day availability
    consecutive_pairs = []
    for i in range(len(available_ordered_days) - 1):
        day1, day2 = available_ordered_days[i], available_ordered_days[i + 1]
        day1_idx = day_order.index(day1)
        day2_idx = day_order.index(day2)
        if day2_idx == day1_idx + 1:
            consecutive_pairs.append((day1, day2))
    
    if consecutive_pairs:
        diagnosis_lines.append("Consecutive day pairs available:")
        for day1, day2 in consecutive_pairs:
            diagnosis_lines.append(f"  {day1} -> {day2}")
    else:
        diagnosis_lines.append("No consecutive days available - this may not be the issue")
    
    diagnosis_lines.extend([
        "",
        "RECOMMENDED SOLUTIONS:",
        "1. Add time slots on non-consecutive days (e.g., Monday, Wednesday, Friday)",
        "2. Consider disabling the 'consecutive days' constraint",
        "3. Review professor availability across different days",
        "4. Reduce classes per week requirements where possible"
    ])
    
    return "\n".join(diagnosis_lines)


def schedule_courses(courses: Dict[str, Dict[str, List[str]]],
                     student_course_map: Dict[str, List[str]],
                     course_professor_map: Dict[str, Union[str, List[str]]],
                     course_classes_per_week: Dict[str, int],
                     course_type: Dict[str, str],
                     non_preferred_slots: List[str],
                     add_prof_constraints: bool = True,
                     add_timeslot_capacity: bool = True,
                     add_student_conflicts: bool = True,
                     add_no_same_day: bool = True,
                     add_no_consec_days: bool = False,                
                     max_classes_per_slot: int = 24) -> tuple[pd.DataFrame, str]:
    """
    Debug-friendly scheduling function with incremental constraint phases:

      PHASE 1) Each course must appear 'classes per week' times.
      PHASE 2) Professor cannot teach two courses in the same slot (AddAtMostOne).
      PHASE 3) Limit each slot to at most max_classes_per_slot classes.
      PHASE 4) Student conflicts (soft) -> penalize scheduling multiple courses for one student in the same slot.
               Additionally, a very soft extra penalty is added if a student's two required courses clash.
      PHASE 5) No same course twice on the same day (hard constraint).
      PHASE 6) No consecutive days constraint (soft penalty).

    If a phase is infeasible, we return an empty DataFrame and an error message.
    If all phases succeed, we return the schedule and success message.

    Returns:
        tuple: (schedule_dataframe, infeasibility_reason_or_success_message)
    """

    # ---------------------------------------------------------
    # Parameters you can tweak
    # ---------------------------------------------------------
    MAX_CLASSES_PER_SLOT = max_classes_per_slot  # Now configurable!
    STUDENT_CONFLICT_WEIGHT = 10000  # penalty weight for each student conflict
    REQUIRED_CONFLICT_WEIGHT = 10  # very soft penalty for a clash between two Required courses
    NON_PREFERRED_SLOTS = 50
    CONSEC_CONFLICT_WEIGHT = 100

    # ---------------------------------------------------------
    # Early validation: Check if we have any time slots at all
    # ---------------------------------------------------------
    all_available_slots = set()
    for course_id, course_info in courses.items():
        all_available_slots.update(course_info.get('time_slots', []))

    if len(all_available_slots) == 0:
        error_msg = ("CRITICAL ERROR: No time slots available across all courses!\n\n"
                    "This usually means:\n"
                    "• No time slots were inserted into the database\n"
                    "• All time slots are blocked by professor busy slots\n"
                    "• Time slot data was not loaded properly\n\n"
                    "Please check the time slot configuration and try again.")
        print(f"[CRITICAL ERROR] {error_msg}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), error_msg

    print(f"[INFO] Found {len(all_available_slots)} unique time slots available for scheduling")

    # ---------------------------------------------------------
    # Quick Pre-Check for "classes per week > available slots" problems
    # ---------------------------------------------------------
    for c_id, info in courses.items():
        needed = course_classes_per_week.get(c_id, 2)  # default if missing
        possible = len(info["time_slots"])
        if needed > possible:
            error_msg = (f"PHASE 1 PRE-CHECK FAILED: Course '{c_id}' needs {needed} sessions "
                        f"but only has {possible} slot(s) available.\n\n"
                        f"Solutions:\n"
                        f"• Add more time slots to the schedule\n"
                        f"• Check if professor busy slots are too restrictive\n"
                        f"• Verify course classes per week requirements are correct")
            print(f"[PRE-CHECK] {error_msg}")
            return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), error_msg

    def solve_phase(
        phase: str,
        add_prof: bool,
        add_cap: bool,
        add_conf: bool,
        add_same: bool,
        add_consec: bool):

        """
        Builds and solves a new model with specified constraints included.
        Returns (status, schedule_df).
        """
        #testing
        conflict_vars          = []
        conflict_required_vars = []
        slot_penalty_vars      = []
        consec_conflict_vars   = []

        model = cp_model.CpModel()

        # Collect all distinct time slots globally
        all_time_slots = set()
        for c_info in courses.values():
            all_time_slots.update(c_info['time_slots'])
        all_time_slots = sorted(all_time_slots)

        # Create bool vars: course_time_vars[c][slot] = 1 if c is in slot
        course_time_vars = {}
        time_slot_count_vars = defaultdict(list)  # for capacity constraints

        for c_id, c_info in courses.items():
            slot_dict = {}
            for slot in c_info['time_slots']:
                var = model.NewBoolVar(f'{c_id}_{slot}')
                slot_dict[slot] = var
                time_slot_count_vars[slot].append(var)
            course_time_vars[c_id] = slot_dict

        # PHASE 1) Each course must appear exactly 'course_classes_per_week[c_id]' times
        for c_id, slot_dict in course_time_vars.items():
            needed = course_classes_per_week.get(c_id, 2)  # fallback if missing
            model.Add(sum(slot_dict.values()) == needed)

        # PHASE 2) Professor constraints
        if add_prof:
            prof_dict = defaultdict(list)
            for c_id, profs in course_professor_map.items():
                # Handle both single professor (string) and multiple professors (list)
                if isinstance(profs, str):
                    profs = [profs]
                elif profs is None:
                    profs = []
                
                # Add course to each professor's list
                for prof in profs:
                    prof_dict[prof].append(c_id)

            for prof, c_list in prof_dict.items():
                # For each time slot, a professor cannot teach more than one course
                slot_map = defaultdict(list)
                for pc_id in c_list:
                    if pc_id in course_time_vars:
                        for s, v in course_time_vars[pc_id].items():
                            slot_map[s].append(v)
                for s, var_list in slot_map.items():
                    if len(var_list) > 1:
                        model.AddAtMostOne(var_list)

        # PHASE 3) Time slot capacity
        if add_cap:
            for slot, var_list in time_slot_count_vars.items():
                model.Add(sum(var_list) <= MAX_CLASSES_PER_SLOT)

        # PHASE 4) Student conflicts (soft)
        conflict_vars = []
        if add_conf:
            for student_id, enrolled in student_course_map.items():
                # Build mapping: time slot -> list of booleans for this student's courses
                slot_map = defaultdict(list)
                for c_id in enrolled:
                    if c_id in course_time_vars:
                        for s, v in course_time_vars[c_id].items():
                            slot_map[s].append(v)
                for s, var_list in slot_map.items():
                    if len(var_list) > 1:
                        # conflict_var = 1 if sum(var_list) >= 2
                        conflict_var = model.NewBoolVar(f'conflict_{student_id}_{s}')
                        model.Add(sum(var_list) >= 2).OnlyEnforceIf(conflict_var)
                        model.Add(sum(var_list) <= 1).OnlyEnforceIf(conflict_var.Not())
                        conflict_vars.append(conflict_var)

        # Additional very soft constraint: Avoid conflict between two Required courses
        conflict_required_vars = []
        if add_same:
            for student_id, enrolled in student_course_map.items():
                # Filter only the courses that are marked as 'Required'
                required_courses = [c_id for c_id in enrolled if course_type.get(c_id, "Elective") == "Required"]
                slot_map_req = defaultdict(list)
                for c_id in required_courses:
                    if c_id in course_time_vars:
                        for s, v in course_time_vars[c_id].items():
                            slot_map_req[s].append(v)
                for s, var_list in slot_map_req.items():
                    if len(var_list) > 1:
                        conflict_req_var = model.NewBoolVar(f'req_conflict_{student_id}_{s}')
                        model.Add(sum(var_list) >= 2).OnlyEnforceIf(conflict_req_var)
                        model.Add(sum(var_list) <= 1).OnlyEnforceIf(conflict_req_var.Not())
                        conflict_required_vars.append(conflict_req_var)

        # PHASE 5) No same course twice on the same day (hard constraint)
        if add_same:
            for c_id, slot_dict in course_time_vars.items():
                # Group the course's slots by day
                day_map = defaultdict(list)
                for s, var in slot_dict.items():
                    day = get_day_from_time_slot(s)
                    day_map[day].append(var)
                # Each day can have at most 1 session of this course
                for day, var_list in day_map.items():
                    if len(var_list) > 1:
                        model.Add(sum(var_list) <= 1)
        
        # PHASE 6) No classes on consecutive days
        if add_consec:
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_to_index = {day: idx for idx, day in enumerate(day_order)}
            
            for c_id, slot_dict in course_time_vars.items():
                day_vars = defaultdict(list) # empty-list as keys; can use append
                for s, var in slot_dict.items(): # Fetches from the slot dictionary of the given course c_id. (s -> slot, var -> CP-SAT BOOL VAR) 
                    day = get_day_from_time_slot(s)
                    day_vars[day].append(var)
                    
                    for i in range(len(day_order)-1):
                        d1, d2 = day_order[i], day_order[i+1]
                        if d1 in day_vars and d2 in day_vars:
                            # indicator if the course is scheduled ANY time on day1 or day2
                            d1_var = model.NewBoolVar(f'{c_id}_on_{d1}')
                            d2_var = model.NewBoolVar(f'{c_id}_on_{d2}')
                            model.AddMaxEquality(d1_var, day_vars[d1])
                            model.AddMaxEquality(d2_var, day_vars[d2])

                            # build a flag that is 1 exactly when both d1_var & d2_var are 1
                            cv = model.NewBoolVar(f'consec_{c_id}_{d1}_{d2}')
                            # cv ⇒ (d1_var AND d2_var)
                            model.AddBoolAnd([d1_var, d2_var]).OnlyEnforceIf(cv)
                            # ¬cv ⇒ (¬d1_var OR ¬d2_var)
                            model.AddBoolOr([d1_var.Not(), d2_var.Not()]).OnlyEnforceIf(cv.Not())
                            consec_conflict_vars.append(cv)
            '''
            for i in range(6): 
                d1, d2 = day_order[i], day_order[i+1] # Fetches consective days 
                if d1 in day_vars and d2 in day_vars:
                    d1_var = model.NewBoolVar(f'{c_id}_on_{d1}')
                    d2_var = model.NewBoolVar(f'{c_id}_on_{d2}')
                    model.AddMaxEquality(d1_var, day_vars[d1]) # Binds each *_var to the list of time slots on that day.
                    model.AddMaxEquality(d2_var, day_vars[d2]) # Same here 
                    #model.Add(d1_var + d2_var <= 1) # The constraint itsel - course can be scheduled on d1 or d2, but not both.'''
                
        slot_penalty_vars = []
        # We retrieve the course_id and the dictionary 
        # with key as the timeslots and the values as the boolean decision variables 
        for c_id, slot_dict in course_time_vars.items(): 
            # We retieve the timeslot and the boolean associated with that
            for s, var in slot_dict.items(): 
                if s in non_preferred_slots: 
                    slot_penalty_vars.append(var)

        # Objective: minimize student conflicts (with additional required course penalty, if any)
        total_penalty = 0
        if conflict_vars:
            total_penalty += STUDENT_CONFLICT_WEIGHT * sum(conflict_vars)
        if conflict_required_vars:
            total_penalty += REQUIRED_CONFLICT_WEIGHT * sum(conflict_required_vars)
        if slot_penalty_vars: 
            total_penalty += NON_PREFERRED_SLOTS * sum(slot_penalty_vars)
        if consec_conflict_vars:
            total_penalty += CONSEC_CONFLICT_WEIGHT * sum(consec_conflict_vars)
        model.Minimize(total_penalty)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0  # 1 minute per phase
        solver.parameters.cp_model_presolve = True
        solver.parameters.linearization_level = 1
        status = solver.Solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Count how many violation vars triggered
            consec_violations = sum(int(solver.Value(cv)) for cv in consec_conflict_vars)
            student_violations = sum(int(solver.Value(v)) for v in conflict_vars)
            required_violations = sum(int(solver.Value(v)) for v in conflict_required_vars)
            nonpref_uses  = sum(int(solver.Value(v)) for v in slot_penalty_vars)
            total_obj     = solver.ObjectiveValue()
            print(f"[METRICS] consec={consec_violations}, student={student_violations},"
                f" required={required_violations}, nonpref={nonpref_uses}, obj={total_obj}")


        schedule_df = pd.DataFrame(columns=["Course ID", "Scheduled Time"])
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            rows = []
            for c_id, slot_dict in course_time_vars.items():
                for s, var in slot_dict.items():
                    if solver.Value(var) == 1:
                        rows.append({"Course ID": c_id, "Scheduled Time": s})
            schedule_df = pd.DataFrame(rows)

        return status, schedule_df

    # ---------------------------------------------------------
    # Phase-by-phase approach
    # ---------------------------------------------------------

    # PHASE 1
    p1_status, p1_df = solve_phase("PHASE 1",
                                   add_prof=False,
                                   add_cap=False,
                                   add_conf=False,
                                   add_same=False,
                                   add_consec=False)
    if p1_status == cp_model.INFEASIBLE:
        detailed_error = diagnose_phase1_conflicts(courses, course_classes_per_week)
        print(f"[DEBUG] {detailed_error}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error

    # PHASE 2
    p2_status, p2_df = solve_phase("PHASE 2",
                                   add_prof=add_prof_constraints,
                                   add_cap=False,
                                   add_conf=False,
                                   add_same=False,
                                   add_consec=False)
    if p2_status == cp_model.INFEASIBLE:
        # Generate detailed diagnostics
        detailed_error = diagnose_phase2_conflicts(courses, course_professor_map, course_classes_per_week)
        print(f"[DEBUG] {detailed_error}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error

    # PHASE 3
    p3_status, p3_df = solve_phase("PHASE 3",
                                   add_prof=add_prof_constraints,
                                   add_cap=add_timeslot_capacity,
                                   add_conf=False,
                                   add_same=False,
                                   add_consec=False)
    if p3_status == cp_model.INFEASIBLE:
        detailed_error = diagnose_phase3_conflicts(courses, course_classes_per_week, MAX_CLASSES_PER_SLOT)
        print(f"[DEBUG] {detailed_error}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error

    # PHASE 4
    p4_status, p4_df = solve_phase("PHASE 4",
                                   add_prof=add_prof_constraints,
                                   add_cap=add_timeslot_capacity,
                                   add_conf=add_student_conflicts,
                                   add_same=False,
                                   add_consec=False)
    if p4_status == cp_model.INFEASIBLE:
        detailed_error = diagnose_phase4_conflicts(courses, course_professor_map)
        print(f"[DEBUG] {detailed_error}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error

    # PHASE 5: No same course twice on the same day
    p5_status, p5_df = solve_phase("PHASE 5",
                                   add_prof=add_prof_constraints,
                                   add_cap=add_timeslot_capacity,
                                   add_conf=add_student_conflicts,
                                   add_same=add_no_same_day,
                                   add_consec=False)
    if p5_status == cp_model.INFEASIBLE:
        detailed_error = diagnose_phase5_conflicts(courses, course_classes_per_week)
        print(f"[DEBUG] {detailed_error}")
        return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error

    print("[DEBUG] Schedule found through PHASE 5 constraints.")
    # PHASE 6: No consecutive days (toggleable)
    if add_no_consec_days:
        p6_status, p6_df = solve_phase("PHASE 6",
                                       add_prof=add_prof_constraints,
                                       add_cap=add_timeslot_capacity,
                                       add_conf=add_student_conflicts,
                                       add_same=add_no_same_day,
                                       add_consec=add_no_consec_days)
        if p6_status == cp_model.INFEASIBLE:
            detailed_error = diagnose_phase6_conflicts(courses, course_classes_per_week)
            print(f"[DEBUG] {detailed_error}")
            return pd.DataFrame(columns=["Course ID", "Scheduled Time"]), detailed_error
        print("[DEBUG] Schedule found through PHASE 6 constraints.")
        return p6_df, "Schedule found through PHASE 6 constraints."

    return p5_df, "Schedule found through PHASE 5 constraints."

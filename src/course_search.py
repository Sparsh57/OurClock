"""
Course Search and Conflict Analysis Module

Provides functionality to search for courses, analyze scheduling conflicts,
and suggest alternative time slots considering student schedules and professor constraints.
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class CourseConflictSearcher:
    """
    A class to search for course schedules and analyze conflicts for specific courses.
    Includes professor busy slot analysis and flexible constraint options.
    """
    
    def __init__(self, schedule_df: pd.DataFrame, student_course_map: Dict, 
                 course_professor_map: Dict = None, professor_busy_slots: Dict = None,
                 course_type_map: Dict = None,
                 ignore_professor_busy_slots: bool = False, ignore_professor_teaching_conflicts: bool = False):
        """
        Initialize the searcher with schedule and student data.
        
        Args:
            schedule_df: DataFrame with schedule data (Course ID, Scheduled Time)
            student_course_map: Dictionary mapping student IDs to their enrolled courses
            course_professor_map: Dictionary mapping courses to their professors
            professor_busy_slots: Dictionary mapping professor names to their busy time slots
            course_type_map: Dictionary mapping course names to their types (Elective, Required, etc.)
            ignore_professor_busy_slots: If True, ignore explicit professor busy slots
            ignore_professor_teaching_conflicts: If True, ignore professor teaching schedule conflicts
        """
        self.schedule_df = schedule_df
        self.student_course_map = student_course_map
        self.course_professor_map = course_professor_map or {}
        self.professor_busy_slots = professor_busy_slots or {}
        self.course_type_map = course_type_map or {}
        self.ignore_professor_busy_slots = ignore_professor_busy_slots
        self.ignore_professor_teaching_conflicts = ignore_professor_teaching_conflicts
        self.schedule_lookup = self._build_schedule_lookup()
        self.student_schedule_lookup = self._build_student_schedule_lookup()
    
    def set_professor_constraint_options(self, ignore_busy_slots: bool = None, 
                                       ignore_teaching_conflicts: bool = None):
        """
        Update professor constraint ignore options.
        
        Args:
            ignore_busy_slots: If provided, updates the ignore_professor_busy_slots setting
            ignore_teaching_conflicts: If provided, updates the ignore_professor_teaching_conflicts setting
        """
        if ignore_busy_slots is not None:
            self.ignore_professor_busy_slots = ignore_busy_slots
        if ignore_teaching_conflicts is not None:
            self.ignore_professor_teaching_conflicts = ignore_teaching_conflicts
    
    def get_professor_constraint_options(self) -> Dict[str, bool]:
        """
        Get current professor constraint ignore options.
        
        Returns:
            Dictionary with current ignore settings
        """
        return {
            'ignore_professor_busy_slots': self.ignore_professor_busy_slots,
            'ignore_professor_teaching_conflicts': self.ignore_professor_teaching_conflicts
        }
    
    def _build_schedule_lookup(self) -> Dict:
        """Build lookup dictionary for course schedules."""
        return self.schedule_df.groupby('Course ID')['Scheduled Time'].apply(list).to_dict()
    
    def _build_student_schedule_lookup(self) -> Dict:
        """Build lookup for each student's complete schedule."""
        student_schedules = {}
        for student_id, courses in self.student_course_map.items():
            student_schedule = defaultdict(list)
            for course in courses:
                if course in self.schedule_lookup:
                    for timeslot in self.schedule_lookup[course]:
                        student_schedule[timeslot].append(course)
            student_schedules[student_id] = dict(student_schedule)
        return student_schedules
    
    def search_course(self, course_name: str) -> Dict:
        """
        Search for a specific course and return detailed information.
        
        Args:
            course_name: Name of the course to search for
            
        Returns:
            Dictionary with course information, schedule, and conflicts
        """
        # Case-insensitive search
        matching_courses = [course for course in self.schedule_lookup.keys() 
                          if course_name.lower() in course.lower()]
        
        if not matching_courses:
            return {
                'found': False,
                'message': f"Course '{course_name}' not found in the schedule.",
                'suggestions': self._get_course_suggestions(course_name)
            }
        
        results = {}
        for course in matching_courses:
            course_info = self._analyze_single_course(course)
            results[course] = course_info
        
        return {
            'found': True,
            'courses': results,
            'total_matches': len(matching_courses)
        }
    
    def _analyze_single_course(self, course_id: str) -> Dict:
        """Analyze a single course for schedule and conflicts."""
        scheduled_slots = self.schedule_lookup.get(course_id, [])
        
        # Find students enrolled in this course
        enrolled_students = [student for student, courses in self.student_course_map.items() 
                           if course_id in courses]
        
        # Get all available time slots from the schedule
        all_time_slots = set()
        for slots in self.schedule_lookup.values():
            all_time_slots.update(slots)
        all_time_slots = sorted(list(all_time_slots))
        
        # Analyze conflicts for current scheduled slots
        current_slot_analysis = {}
        total_conflicts = 0
        conflicted_students = set()
        
        for slot in scheduled_slots:
            slot_conflicts = self._analyze_slot_conflicts(course_id, slot)
            current_slot_analysis[slot] = slot_conflicts
            total_conflicts += len(slot_conflicts['conflicted_students'])
            conflicted_students.update(slot_conflicts['conflicted_students'])
        
        # Analyze what would happen if course was scheduled in each available slot
        alternative_slot_analysis = {}
        for slot in all_time_slots:
            if slot not in scheduled_slots:  # Only analyze unscheduled slots
                potential_conflicts = self._analyze_potential_slot_conflicts(course_id, slot, enrolled_students)
                # Only include slots where professor is available
                if potential_conflicts['professor_available']:
                    alternative_slot_analysis[slot] = potential_conflicts
                else:
                    # Add professor constraint information for unavailable slots
                    potential_conflicts['excluded_reason'] = 'Professor unavailable'
                    alternative_slot_analysis[slot] = potential_conflicts
        
        return {
            'course_id': course_id,
            'scheduled_slots': scheduled_slots,
            'total_enrolled_students': len(enrolled_students),
            'enrolled_students': enrolled_students,
            'total_conflicted_students': len(conflicted_students),
            'conflicted_students': list(conflicted_students),
            'conflict_rate': (len(conflicted_students) / len(enrolled_students) * 100) if enrolled_students else 0,
            'current_slot_analysis': current_slot_analysis,
            'alternative_slot_analysis': alternative_slot_analysis,
            'all_available_slots': all_time_slots,
            'has_conflicts': total_conflicts > 0
        }
    
    def _analyze_slot_conflicts(self, course_id: str, time_slot: str) -> Dict:
        """Analyze conflicts for a specific course in a specific time slot."""
        conflicts = []
        conflicted_students = []
        
        # Find all students taking this course
        course_students = [student for student, courses in self.student_course_map.items() 
                          if course_id in courses]
        
        # Check professor availability for this slot
        professor_available = self._is_professor_available(course_id, time_slot)
        
        for student in course_students:
            student_schedule = self.student_schedule_lookup.get(student, {})
            slot_courses = student_schedule.get(time_slot, [])
            
            # If student has multiple courses in this slot
            if len(slot_courses) > 1:
                conflicting_courses = [c for c in slot_courses if c != course_id]
                if conflicting_courses:
                    # Add course type information to conflicting courses
                    conflicting_courses_with_types = []
                    for conflicting_course in conflicting_courses:
                        course_type = self.course_type_map.get(conflicting_course, 'Unknown')
                        conflicting_courses_with_types.append({
                            'course_name': conflicting_course,
                            'course_type': course_type
                        })
                    
                    conflicts.append({
                        'student_id': student,
                        'conflicting_courses': conflicting_courses,  # Keep original for backward compatibility
                        'conflicting_courses_with_types': conflicting_courses_with_types,
                        'all_courses_in_slot': slot_courses,
                        'conflict_type': 'concurrent_enrollment',
                        'time_slot': time_slot
                    })
                    conflicted_students.append(student)
        
        return {
            'time_slot': time_slot,
            'total_conflicts': len(conflicts),
            'conflicted_students': conflicted_students,
            'conflict_details': conflicts,
            'is_conflict_free': len(conflicts) == 0,
            'professor_available': professor_available,
            'professor_constraint_violated': not professor_available,
            'total_enrolled': len(course_students),
            'conflict_free_students': len(course_students) - len(conflicted_students),
            'conflict_rate': len(conflicts) / len(course_students) if course_students else 0
        }
    
    def _analyze_potential_slot_conflicts(self, course_id: str, time_slot: str, enrolled_students: List[str]) -> Dict:
        """Analyze what conflicts would occur if course was scheduled in this slot."""
        potential_conflicts = []
        conflicted_students = []
        
        # Check professor availability
        professor_available = self._is_professor_available(course_id, time_slot)
        
        for student in enrolled_students:
            student_schedule = self.student_schedule_lookup.get(student, {})
            existing_courses_in_slot = student_schedule.get(time_slot, [])
            
            # If student already has courses in this slot, there would be a conflict
            if existing_courses_in_slot:
                # Add course type information to conflicting courses
                conflicting_courses_with_types = []
                for conflicting_course in existing_courses_in_slot:
                    course_type = self.course_type_map.get(conflicting_course, 'Unknown')
                    conflicting_courses_with_types.append({
                        'course_name': conflicting_course,
                        'course_type': course_type
                    })
                
                potential_conflicts.append({
                    'student_id': student,
                    'conflicting_courses': existing_courses_in_slot,  # Keep original for backward compatibility
                    'conflicting_courses_with_types': conflicting_courses_with_types,
                    'would_conflict_with': existing_courses_in_slot,
                    'conflict_type': 'student_schedule_conflict'
                })
                conflicted_students.append(student)
        
        return {
            'time_slot': time_slot,
            'potential_conflicts': len(potential_conflicts),
            'would_be_conflicted_students': conflicted_students,
            'conflict_details': potential_conflicts,
            'would_be_conflict_free': len(potential_conflicts) == 0 and professor_available,
            'conflict_free_students': len(enrolled_students) - len(conflicted_students),
            'total_enrolled': len(enrolled_students),
            'professor_available': professor_available,
            'professor_constraint': not professor_available,
            'student_conflicts': potential_conflicts,  # Detailed conflict info
            'conflict_rate': len(potential_conflicts) / len(enrolled_students) if enrolled_students else 0
        }
    
    def _is_professor_available(self, course_id: str, time_slot: str) -> bool:
        """
        Check if the professor assigned to this course is available at the given time slot.
        Checks both explicit busy slots AND actual teaching schedule conflicts.
        Respects ignore options for different types of professor constraints.
        """
        if not self.course_professor_map:
            return True  # No professor data available, assume available
        
        course_professors = self.course_professor_map.get(course_id, [])
        if not course_professors:
            return True  # No professor assigned, assume available
        
        # Handle both single professor (string) and multiple professors (list)
        if isinstance(course_professors, str):
            course_professors = [course_professors]
        
        # Check if any assigned professor has conflicts
        for professor in course_professors:
            # Check 1: Explicit busy slots (unless ignored)
            if not self.ignore_professor_busy_slots and self.professor_busy_slots:
                professor_busy_times = self.professor_busy_slots.get(professor, [])
                if time_slot in professor_busy_times:
                    return False  # Professor is explicitly marked as busy
            
            # Check 2: Teaching schedule conflicts (unless ignored)
            if not self.ignore_professor_teaching_conflicts and self.course_professor_map:
                # Look through all courses to see if this professor is teaching something else at this time
                for other_course_id, other_professors in self.course_professor_map.items():
                    if other_course_id == course_id:
                        continue  # Skip the same course
                    
                    # Handle both string and list formats for other course professors
                    if isinstance(other_professors, str):
                        other_professors = [other_professors]
                    
                    # If this professor teaches the other course
                    if professor in other_professors:
                        # Check if the other course is scheduled at this time slot
                        other_course_schedule = self.schedule_lookup.get(other_course_id, [])
                        if time_slot in other_course_schedule:
                            return False  # Professor is teaching another course at this time
        
        return True  # All professors are available
    
    def _get_course_suggestions(self, course_name: str) -> List[str]:
        """Get suggestions for similar course names."""
        all_courses = list(self.schedule_lookup.keys())
        suggestions = []
        
        # Find courses that contain any part of the search term
        search_parts = course_name.lower().split()
        for course in all_courses:
            course_lower = course.lower()
            if any(part in course_lower for part in search_parts):
                suggestions.append(course)
        
        return suggestions[:5]  # Return top 5 suggestions
    
    def get_all_courses(self) -> List[str]:
        """Get list of all available courses."""
        return sorted(list(self.schedule_lookup.keys()))
    
    def get_course_summary_table(self) -> pd.DataFrame:
        """Generate a summary table of all courses with conflict information."""
        summary_data = []
        
        for course_id in self.schedule_lookup.keys():
            course_info = self._analyze_single_course(course_id)
            summary_data.append({
                'Course ID': course_id,
                'Scheduled Slots': len(course_info['scheduled_slots']),
                'Time Slots': ', '.join(course_info['scheduled_slots']),
                'Total Students': course_info['total_enrolled_students'],
                'Conflicted Students': course_info['total_conflicted_students'],
                'Conflict Rate (%)': f"{course_info['conflict_rate']:.1f}%",
                'Has Conflicts': 'Yes' if course_info['has_conflicts'] else 'No'
            })
        
        df = pd.DataFrame(summary_data)
        return df.sort_values('Conflicted Students', ascending=False)


def format_course_search_results(search_results: Dict) -> str:
    """
    Format course search results for display.
    
    Args:
        search_results: Results from CourseConflictSearcher.search_course()
        
    Returns:
        Formatted string for display
    """
    if not search_results['found']:
        output = [f"❌ {search_results['message']}"]
        if search_results.get('suggestions'):
            output.append("\n💡 Did you mean one of these courses?")
            for suggestion in search_results['suggestions']:
                output.append(f"   • {suggestion}")
        return '\n'.join(output)
    
    output = [f"✅ Found {search_results['total_matches']} matching course(s):\n"]
    
    for course_id, info in search_results['courses'].items():
        output.append(f"📚 COURSE: {course_id}")
        output.append("=" * 50)
        
        # Basic info
        output.append(f"📅 Scheduled Time Slots: {len(info['scheduled_slots'])}")
        for i, slot in enumerate(info['scheduled_slots'], 1):
            conflict_info = info['current_slot_analysis'][slot]
            status = "✅ No conflicts" if conflict_info['is_conflict_free'] else f"⚠️  {conflict_info['total_conflicts']} conflicts"
            output.append(f"   {i}. {slot} - {status}")
        
        # Student information
        output.append(f"\n👥 Student Enrollment:")
        output.append(f"   Total Enrolled: {info['total_enrolled_students']}")
        output.append(f"   With Conflicts: {info['total_conflicted_students']}")
        output.append(f"   Conflict Rate: {info['conflict_rate']:.1f}%")
        
        # Conflict details
        if info['has_conflicts']:
            output.append(f"\n⚠️  CURRENT SCHEDULE CONFLICTS:")
            for slot, slot_info in info['current_slot_analysis'].items():
                if not slot_info['is_conflict_free']:
                    output.append(f"\n   📍 Time Slot: {slot}")
                    for conflict in slot_info['conflict_details']:
                        student = conflict['student_id']
                        conflicting = ', '.join(conflict['conflicting_courses'])
                        output.append(f"      • Student {student}: Conflicts with {conflicting}")
        else:
            output.append(f"\n🎉 No scheduling conflicts found for this course!")
        
        # Alternative slots analysis
        if info['alternative_slot_analysis']:
            output.append(f"\n🔄 ALTERNATIVE TIME SLOT ANALYSIS:")
            # Sort by number of conflicts (best first)
            sorted_alternatives = sorted(info['alternative_slot_analysis'].items(), 
                                       key=lambda x: x[1]['potential_conflicts'])
            
            for slot, slot_info in sorted_alternatives[:5]:  # Show top 5 alternatives
                conflict_rate = (slot_info['potential_conflicts'] / slot_info['total_enrolled'] * 100) if slot_info['total_enrolled'] > 0 else 0
                status = "✅ CONFLICT-FREE" if slot_info['would_be_conflict_free'] else f"⚠️  {slot_info['potential_conflicts']} conflicts"
                output.append(f"\n   📍 {slot}: {status} ({conflict_rate:.1f}% conflict rate)")
                output.append(f"      → {slot_info['conflict_free_students']} students would be conflict-free")
                
                if not slot_info['would_be_conflict_free'] and len(slot_info['conflict_details']) <= 3:
                    for conflict in slot_info['conflict_details']:
                        student = conflict['student_id']
                        conflicting = ', '.join(conflict['conflicting_courses'])
                        output.append(f"      • Student {student} would conflict with {conflicting}")
        
        output.append("\n" + "=" * 50 + "\n")
    
    return '\n'.join(output)


def search_course_interactive(schedule_df: pd.DataFrame, student_course_map: Dict, course_name: str) -> str:
    """
    Interactive course search function that returns formatted results.
    
    Args:
        schedule_df: DataFrame with schedule data
        student_course_map: Dictionary mapping students to courses
        course_name: Name of course to search for
        
    Returns:
        Formatted search results as string
    """
    searcher = CourseConflictSearcher(schedule_df, student_course_map)
    results = searcher.search_course(course_name)
    return format_course_search_results(results)


def get_course_list(schedule_df: pd.DataFrame) -> List[str]:
    """
    Get a list of all available courses from the schedule.
    
    Args:
        schedule_df: DataFrame with schedule data
        
    Returns:
        Sorted list of course names
    """
    return sorted(schedule_df['Course ID'].unique().tolist())


def generate_course_summary_report(schedule_df: pd.DataFrame, student_course_map: Dict) -> pd.DataFrame:
    """
    Generate a summary report of all courses with conflict information.
    
    Args:
        schedule_df: DataFrame with schedule data
        student_course_map: Dictionary mapping students to courses
        
    Returns:
        DataFrame with course summary information
    """
    searcher = CourseConflictSearcher(schedule_df, student_course_map)
    return searcher.get_course_summary_table()
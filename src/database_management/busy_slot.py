from .dbconnection import get_db_session, create_tables, is_postgresql, get_organization_database_url
from .models import User, Slot, ProfessorBusySlot
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def insert_professor_busy_slots(file, db_path):
    """
    Inserts professor busy slots from a CSV file using bulk operations.

    :param file: The CSV file containing faculty preferences.
    :param db_path: Path to the database file or schema identifier.
    """
    df_courses = file
    logger.info(f"Starting bulk busy slot insertion for database: {db_path}")
    
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix

    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM \"Professor_BusySlots\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM Professor_BusySlots LIMIT 1"))
    except Exception:
        # If table doesn't exist, create all tables
        logger.info("Professor_BusySlots table not found, creating tables...")
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
            # Fetch professors and slots
            professors = session.query(User).filter_by(Role='Professor').all()
            slots = session.query(Slot).all()
            
            # Create dictionaries for mapping (case-insensitive for professors)
            prof_dict = {prof.Email.lower(): prof.UserID for prof in professors}
            slot_dict = {f"{slot.Day} {slot.StartTime}": slot.SlotID for slot in slots}

            # Process the data and prepare for bulk insert
            df_merged = df_courses[['Name', 'Busy Slot']].copy()
            busy_slots_to_insert = []
            
            for index, row in df_merged.iterrows():
                try:
                    prof_id = prof_dict.get(row['Name'].lower() if pd.notna(row['Name']) else '')
                    slot_id = slot_dict.get(row['Busy Slot'])
                    
                    if prof_id and slot_id:
                        busy_slots_to_insert.append({
                            'ProfessorID': prof_id,
                            'SlotID': slot_id
                        })
                    else:
                        if not prof_id:
                            logger.warning(f"Professor '{row['Name']}' not found in database")
                        if not slot_id:
                            logger.warning(f"Slot '{row['Busy Slot']}' not found in database")
                            
                except Exception as e:
                    logger.error(f"Error processing row {index}: {e}")

            # Remove duplicates within the current batch first
            seen_combinations = set()
            deduplicated_slots = []
            for slot in busy_slots_to_insert:
                combo = (slot['ProfessorID'], slot['SlotID'])
                if combo not in seen_combinations:
                    seen_combinations.add(combo)
                    deduplicated_slots.append(slot)

            logger.info(f"Removed {len(busy_slots_to_insert) - len(deduplicated_slots)} duplicate entries from current batch")

            # Use PostgreSQL's ON CONFLICT for robust duplicate handling
            if deduplicated_slots:
                if is_postgresql():
                    # Use raw SQL with ON CONFLICT for PostgreSQL
                    insert_stmt = text("""
                        INSERT INTO "Professor_BusySlots" ("ProfessorID", "SlotID") 
                        VALUES (:ProfessorID, :SlotID) 
                        ON CONFLICT ("ProfessorID", "SlotID") DO NOTHING
                    """)
                    session.execute(insert_stmt, deduplicated_slots)
                else:
                    # For SQLite, use the existing approach with duplicate checking
                    existing_busy_slots = set()
                    for busy_slot in session.query(ProfessorBusySlot).all():
                        existing_busy_slots.add((busy_slot.ProfessorID, busy_slot.SlotID))

                    # Filter out existing busy slots
                    new_busy_slots = [
                        slot for slot in deduplicated_slots
                        if (slot['ProfessorID'], slot['SlotID']) not in existing_busy_slots
                    ]
                    
                    if new_busy_slots:
                        session.bulk_insert_mappings(ProfessorBusySlot, new_busy_slots)

                session.commit()
                logger.info(f"Successfully processed {len(deduplicated_slots)} professor busy slots")
                print(f"Successfully processed {len(deduplicated_slots)} professor busy slots.")
            else:
                logger.info("No professor busy slots to insert")
                print("No professor busy slots to insert.")

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error bulk inserting busy slots: {e}")
            raise


def empty_professor_busy_slots(db_path):
    """
    Empties all records from the Professor_BusySlots table using SQLAlchemy.
    
    :param db_path: Path to the database file or schema identifier.
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix
    
    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM \"Professor_BusySlots\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM Professor_BusySlots LIMIT 1"))
    except Exception:
        # If table doesn't exist, create all tables
        logger.info("Professor_BusySlots table not found, creating tables...")
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
            deleted_count = session.query(ProfessorBusySlot).delete()
            session.commit()
            logger.info(f"Deleted {deleted_count} professor busy slot records")
            print(f"All {deleted_count} records deleted successfully from Professor_BusySlots.")
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error deleting busy slots: {e}")
            raise


def fetch_professor_busy_slots(db_path):
    """
    Fetches all records from the Professor_BusySlots table using SQLAlchemy.

    :param db_path: Path to the database file or schema identifier.
    :return: List of tuples (ProfessorID, SlotID).
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix
    
    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM \"Professor_BusySlots\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM Professor_BusySlots LIMIT 1"))
    except Exception:
        # If table doesn't exist, create all tables
        logger.info("Professor_BusySlots table not found, creating tables...")
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
            busy_slots = session.query(ProfessorBusySlot).all()
            result = [(bs.ProfessorID, bs.SlotID) for bs in busy_slots]
            print(result)
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error fetching busy slots: {e}")
            return []


def insert_professor_busy_slots_from_ui(slots, professor_id, db_path):
    """
    Inserts professor busy slots into the database from UI input using SQLAlchemy.

    :param slots: List of SlotIDs.
    :param professor_id: Professor's UserID.
    :param db_path: Path to the database file or schema identifier.
    """
    # Auto-detect org_name from db_path if it's a schema path
    org_name = None
    if db_path and db_path.startswith("schema:"):
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            org_name = schema_name[4:]  # Remove 'org_' prefix
    
    # First, ensure tables exist
    try:
        if is_postgresql() and org_name:
            with get_db_session(get_organization_database_url(), org_name) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM \"Professor_BusySlots\" LIMIT 1"))
        else:
            with get_db_session(db_path) as session:
                # Check if Professor_BusySlots table exists by querying it
                session.execute(text("SELECT 1 FROM Professor_BusySlots LIMIT 1"))
    except Exception:
        # If table doesn't exist, create all tables
        logger.info("Professor_BusySlots table not found, creating tables...")
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
            # Remove duplicates from input slots
            unique_slots = list(set(slots))
            
            # Prepare data for bulk insert
            busy_slots_data = [
                {'ProfessorID': professor_id, 'SlotID': slot_id}
                for slot_id in unique_slots
            ]
            
            if busy_slots_data:
                if is_postgresql():
                    # Use raw SQL with ON CONFLICT for PostgreSQL
                    insert_stmt = text("""
                        INSERT INTO "Professor_BusySlots" ("ProfessorID", "SlotID") 
                        VALUES (:ProfessorID, :SlotID) 
                        ON CONFLICT ("ProfessorID", "SlotID") DO NOTHING
                    """)
                    session.execute(insert_stmt, busy_slots_data)
                else:
                    # For SQLite, check for existing entries
                    for slot_id in unique_slots:
                        existing = session.query(ProfessorBusySlot).filter_by(
                            ProfessorID=professor_id, SlotID=slot_id).first()
                        
                        if not existing:
                            new_busy_slot = ProfessorBusySlot(
                                ProfessorID=professor_id,
                                SlotID=slot_id
                            )
                            session.add(new_busy_slot)
                    
            session.commit()
            logger.info(f"Processed {len(unique_slots)} busy slots for professor {professor_id}")
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error inserting busy slots from UI: {e}")
            raise


def fetch_user_id(email, db_path):
    """
    Fetches the UserID of a professor based on email using SQLAlchemy.

    :param email: Email of the professor.
    :param db_path: Path to the database file or schema identifier.
    :return: UserID of the professor or None.
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
            user = session.query(User).filter_by(Email=email).first()
            return user.UserID if user else None
        except SQLAlchemyError as e:
            logger.error(f"Error fetching user ID: {e}")
            return None




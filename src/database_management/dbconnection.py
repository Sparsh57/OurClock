import os
from sqlalchemy import create_engine, text, MetaData
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from .models import Base, MetaBase, Organization
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """
    Get the database URL from environment variables.
    Falls back to SQLite if no DATABASE_URL is provided.
    
    :return: Database URL string
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Handle Heroku postgres URLs (postgresql:// -> postgresql+psycopg2://)
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return database_url
    else:
        # Default to SQLite meta database
        return "sqlite:///organizations_meta.db"


def get_organization_database_url(org_name: str = None, db_path: str = None) -> str:
    """
    Get the database URL for an organization.
    In PostgreSQL mode, uses schemas. In SQLite mode, uses separate files.
    
    :param org_name: Organization name (for schema-based approach)
    :param db_path: Database path (for SQLite file-based approach)
    :return: Database URL string
    """
    base_database_url = os.getenv("DATABASE_URL")
    
    if base_database_url:
        # PostgreSQL mode - use schemas
        if base_database_url.startswith("postgres://"):
            base_database_url = base_database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif base_database_url.startswith("postgresql://"):
            base_database_url = base_database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        
        # For PostgreSQL, we'll use the same database but different schemas
        # The schema separation will be handled at the application level
        return base_database_url
    else:
        # SQLite mode - use separate files
        if db_path:
            return f"sqlite:///{db_path}"
        elif org_name:
            safe_org_name = org_name.replace(' ', '_').replace('/', '_')
            return f"sqlite:///data/{safe_org_name}.db"
        else:
            return "sqlite:///organizations_meta.db"


def is_postgresql() -> bool:
    """
    Check if we're using PostgreSQL.
    
    :return: True if using PostgreSQL, False if using SQLite
    """
    database_url = os.getenv("DATABASE_URL")
    return database_url and (database_url.startswith("postgres") or "postgresql" in database_url)


def get_schema_for_organization(org_name: str) -> str:
    """
    Get the schema name for an organization.
    Only used in PostgreSQL mode.
    
    :param org_name: Organization name
    :return: Schema name
    """
    if not is_postgresql():
        return None
    
    # Convert org name to a valid schema name
    safe_name = org_name.lower().replace(' ', '_').replace('-', '_')
    # Remove any characters that aren't alphanumeric or underscore
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
    return f"org_{safe_name}"


def extract_org_name_from_db_path(db_path: str) -> str:
    """
    Extract organization name from database path.
    For PostgreSQL schema paths, extract from 'schema:org_name' format.
    For SQLite, this returns None as org_name isn't needed.
    
    :param db_path: Database path or schema identifier
    :return: Organization name or None
    """
    if db_path and db_path.startswith("schema:"):
        # Extract org name from schema path
        schema_name = db_path.replace("schema:", "")
        if schema_name.startswith("org_"):
            return schema_name[4:]  # Remove 'org_' prefix
    return None


def create_database_engine(db_path_or_url: str, **kwargs):
    """
    Creates a SQLAlchemy engine for the given database path or URL.
    
    :param db_path_or_url: Path to SQLite database file or PostgreSQL URL
    :param kwargs: Additional engine parameters
    :return: SQLAlchemy engine
    """
    # Determine if this is a URL or a file path
    if db_path_or_url.startswith(('sqlite://', 'postgresql+psycopg2://', 'postgresql://', 'postgres://')):
        database_url = db_path_or_url
    else:
        # Assume it's a SQLite file path
        database_url = f'sqlite:///{db_path_or_url}'
    
    # Handle different database types
    if database_url.startswith('sqlite://'):
        # SQLite specific configuration
        engine = create_engine(
            database_url,
            echo=kwargs.get('echo', False),
            connect_args={
                'check_same_thread': False,
                'timeout': 30
            }
        )
    else:
        # PostgreSQL specific configuration
        engine = create_engine(
            database_url,
            echo=kwargs.get('echo', False),
            pool_size=kwargs.get('pool_size', 10),
            max_overflow=kwargs.get('max_overflow', 20),
            pool_pre_ping=True,
            pool_recycle=300
        )
    
    return engine


def create_schema_if_not_exists(engine, schema_name: str):
    """
    Create a schema if it doesn't exist (PostgreSQL only).
    
    :param engine: SQLAlchemy engine
    :param schema_name: Name of the schema to create
    """
    if schema_name and is_postgresql():
        # Use autocommit for DDL operations
        with engine.connect().execution_options(autocommit=True) as conn:
            # Check if schema exists
            result = conn.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = :schema_name"
            ), {"schema_name": schema_name})
            
            if not result.fetchone():
                # Create schema
                conn.execute(text(f"CREATE SCHEMA {schema_name}"))
                logger.info(f"Created schema: {schema_name}")


def create_tables(db_path_or_url: str, org_name: str = None):
    """
    Creates all tables defined in the models for the given database.
    
    :param db_path_or_url: Path to SQLite database file or organization database URL
    :param org_name: Organization name (used for schema in PostgreSQL)
    """
    if is_postgresql() and org_name:
        # PostgreSQL with organization schema
        engine = create_database_engine(get_organization_database_url())
        schema_name = get_schema_for_organization(org_name)
        
        # Create schema if it doesn't exist
        create_schema_if_not_exists(engine, schema_name)
        
        # Create tables in the schema
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Create a temporary metadata object with schema-specific tables
                # This avoids polluting the global metadata
                schema_metadata = MetaData()
                
                # Copy tables to schema metadata with the correct schema
                for table in Base.metadata.tables.values():
                    table.to_metadata(schema_metadata, schema=schema_name)
                
                # Use autocommit for DDL operations to ensure tables are committed
                with engine.connect().execution_options(autocommit=True) as conn:
                    # Set search path
                    conn.execute(text(f"SET search_path TO {schema_name}, public"))
                    # Create all tables using the connection
                    schema_metadata.create_all(conn)
                
                logger.info(f"Created tables for organization: {org_name} in schema: {schema_name}")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Table creation attempt {attempt + 1} failed, retrying: {e}")
                    time.sleep(1)
                else:
                    logger.error(f"Failed to create tables after {max_retries} attempts: {e}")
                    raise
    else:
        # SQLite or PostgreSQL without organization schema
        engine = create_database_engine(db_path_or_url)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                Base.metadata.create_all(engine)
                logger.info(f"Created tables for database: {db_path_or_url}")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Table creation attempt {attempt + 1} failed, retrying: {e}")
                    time.sleep(1)
                else:
                    logger.error(f"Failed to create tables after {max_retries} attempts: {e}")
                    raise
    
    engine.dispose()


def create_meta_tables(meta_db_url: str = None):
    """
    Creates all tables for the meta-database.
    
    :param meta_db_url: URL for the meta-database
    """
    if meta_db_url is None:
        meta_db_url = get_database_url()
    
    engine = create_database_engine(meta_db_url)
    
    if is_postgresql():
        # For PostgreSQL, create a dedicated schema for meta tables
        create_schema_if_not_exists(engine, "meta")
        
        # Create a temporary metadata object for meta schema
        meta_schema_metadata = MetaData()
        
        # Copy tables to meta schema metadata with the correct schema
        for table in MetaBase.metadata.tables.values():
            table.to_metadata(meta_schema_metadata, schema="meta")
        
        try:
            meta_schema_metadata.create_all(engine)
            logger.info(f"Created meta-database tables: {meta_db_url}")
        finally:
            engine.dispose()
    else:
        try:
            MetaBase.metadata.create_all(engine)
            logger.info(f"Created meta-database tables: {meta_db_url}")
        finally:
            engine.dispose()


@contextmanager
def get_db_session(db_path_or_url: str, org_name: str = None) -> Session:
    """
    Context manager that provides a SQLAlchemy session for the given database.
    Automatically handles session cleanup and rollback on errors.
    
    :param db_path_or_url: Path to SQLite database file or database URL
    :param org_name: Organization name (used for schema in PostgreSQL)
    :yield: SQLAlchemy session
    """
    if is_postgresql() and org_name:
        # PostgreSQL with schema
        engine = create_database_engine(get_organization_database_url())
        schema_name = get_schema_for_organization(org_name)
        
        # Set the search path to include the organization schema
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        
        if schema_name:
            try:
                session.execute(text(f"SET search_path TO {schema_name}, public"))
            except Exception as e:
                logger.warning(f"Could not set search path to {schema_name}: {e}")
    else:
        # SQLite or PostgreSQL without schema
        engine = create_database_engine(db_path_or_url)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
    
    try:
        yield session
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()
        engine.dispose()


@contextmanager
def get_meta_db_session(meta_db_url: str = None) -> Session:
    """
    Context manager that provides a SQLAlchemy session for the meta-database.
    
    :param meta_db_url: URL for the meta-database
    :yield: SQLAlchemy session
    """
    if meta_db_url is None:
        meta_db_url = get_database_url()
    
    engine = create_database_engine(meta_db_url)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    if is_postgresql():
        # Set search path to meta schema
        try:
            session.execute(text("SET search_path TO meta, public"))
        except Exception as e:
            logger.warning(f"Could not set search path to meta schema: {e}")
    
    try:
        yield session
    except Exception as e:
        session.rollback()
        logger.error(f"Meta-database session error: {e}")
        raise
    finally:
        session.close()
        engine.dispose()


def get_organization_by_domain(email_domain: str, meta_db_url: str = None):
    """
    Get organization information by email domain using SQLAlchemy.
    
    :param email_domain: Email domain to search for
    :param meta_db_url: URL for the meta-database
    :return: Organization object or None
    """
    with get_meta_db_session(meta_db_url) as session:
        try:
            organizations = session.query(Organization).all()
            for org in organizations:
                allowed_domains = [d.strip() for d in org.OrgDomains.split(",")]
                if any(email_domain.endswith(f"@{domain}") for domain in allowed_domains):
                    return org
            return None
        except Exception as e:
            logger.error(f"Error finding organization by domain: {e}")
            return None


def get_all_organizations(meta_db_url: str = None):
    """
    Get all organizations from the meta-database using SQLAlchemy.
    
    :param meta_db_url: URL for the meta-database
    :return: List of Organization objects
    """
    with get_meta_db_session(meta_db_url) as session:
        try:
            return session.query(Organization).all()
        except Exception as e:
            logger.error(f"Error fetching organizations: {e}")
            return []


def get_organization_by_name(org_name: str, meta_db_url: str = None):
    """
    Get organization information by name using SQLAlchemy.
    
    :param org_name: Name of the organization
    :param meta_db_url: URL for the meta-database
    :return: Organization object or None
    """
    with get_meta_db_session(meta_db_url) as session:
        try:
            return session.query(Organization).filter_by(OrgName=org_name).first()
        except Exception as e:
            logger.error(f"Error finding organization by name: {e}")
            return None


class DatabaseManager:
    """
    A class to manage database operations using SQLAlchemy.
    """
    
    def __init__(self, db_path_or_url: str, org_name: str = None):
        self.db_path_or_url = db_path_or_url
        self.org_name = org_name
        self.engine = create_database_engine(db_path_or_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def create_tables(self):
        """Create all tables defined in the models."""
        if is_postgresql() and self.org_name:
            schema_name = get_schema_for_organization(self.org_name)
            create_schema_if_not_exists(self.engine, schema_name)
            
            # Create a temporary metadata object with schema-specific tables
            schema_metadata = MetaData()
            
            # Copy tables to schema metadata with the correct schema
            for table in Base.metadata.tables.values():
                table.to_metadata(schema_metadata, schema=schema_name)
            
            schema_metadata.create_all(self.engine)
        else:
            Base.metadata.create_all(self.engine)
        
        logger.info(f"Created tables for database: {self.db_path_or_url}")
    
    def get_session(self) -> Session:
        """Get a new database session."""
        session = self.SessionLocal()
        
        if is_postgresql() and self.org_name:
            schema_name = get_schema_for_organization(self.org_name)
            if schema_name:
                try:
                    session.execute(text(f"SET search_path TO {schema_name}, public"))
                except Exception as e:
                    logger.warning(f"Could not set search path to {schema_name}: {e}")
        
        return session
    
    @contextmanager
    def session_scope(self):
        """Context manager for database sessions."""
        session = self.get_session()
        try:
            yield session
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close() 
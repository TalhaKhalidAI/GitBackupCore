import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from App.api.dependencies.sqlite_connector import Base, engine

# Import all models (each once, with consistent naming)
from App.api.databases.Users import User
from App.api.databases.Repository import Repository
from App.api.databases.UserRepo import userRepo
from App.api.databases.sshKeys import SSHKey
from App.api.databases.backupSnapshot import BackupSnapshot
from App.api.databases.BackupJobs import BackupJob
from App.api.databases.RetentionPolicy import RetentionPolicy
from App.api.databases.AlertRule import AlertRule
from App.api.databases.AccessLog import AccessLog
from App.api.databases.QuotaUsage import QuotaUsage

def run_migration():
    """Create all database tables."""
    print("=" * 50)
    print("🚀 Running Database Migration...")
    print("=" * 50)
    
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        # Verify tables created
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        print(f"\n✅ Successfully created {len(tables)} tables:")
        for table in sorted(tables):
            print(f"   📁 {table}")
        
        print("\n🎉 Migration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

def reset_database():
    """WARNING: Drop all tables and recreate."""
    print("=" * 50)
    print("⚠️  WARNING: This will DELETE ALL DATA! ⚠️")
    print("=" * 50)
    
    confirm = input("Type 'YES' to confirm: ")
    if confirm != "YES":
        print("❌ Reset cancelled.")
        return
    
    try:
        # Drop all tables
        Base.metadata.drop_all(bind=engine)
        print("✅ All tables dropped.")
        
        # Recreate
        run_migration()
        
    except Exception as e:
        print(f"❌ Reset failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_database()
    else:
        run_migration()
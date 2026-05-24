import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app, init_db
if __name__ == '__main__':
    with app.app_context():
        init_db()
        print("✅ Database initialized!")
        print("✅ Admin: admin@elearn.com / admin123")

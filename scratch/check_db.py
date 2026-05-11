import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configuracao.settings')
django.setup()

from django.db import connections

try:
    cursor = connections['banco_teste'].cursor()
    cursor.execute("SHOW TABLES;")
    tables = cursor.fetchall()
    print("Tables in banco_teste:", tables)
except Exception as e:
    print("Error:", e)

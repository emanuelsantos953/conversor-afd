import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configuracao.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
import traceback

try:
    user = User.objects.get(username='apresentacao')
    client = Client(HTTP_HOST='localhost')
    client.force_login(user)
    response = client.get('/gerenciar/')
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Success! 200 OK.")
    else:
        print(response.content)
except Exception as e:
    traceback.print_exc()

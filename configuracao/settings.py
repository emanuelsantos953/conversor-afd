from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-)3-n%&ge+zyi=mnexw00g6e)i1)prwfx5oo3vtk$4%25y*a3*#'

# SEGURANÇA: DEBUG desligado para produção
DEBUG = False

# Adicionamos seu IP público e o IP interno aqui
ALLOWED_HOSTS = ['192.168.0.9', 'localhost', '45.163.40.74', 'sistemasweb.taquarituba.sp.gov.br']

# Adicionamos origens confiáveis para que o Django aceite requisições (como o login) de acessos externos
CSRF_TRUSTED_ORIGINS = [
    'http://45.163.40.74:9445',
    'https://45.163.40.74:9445',
    'http://45.163.40.74',
    'https://45.163.40.74',
    'http://192.168.0.9',
    'https://192.168.0.9',
    'https://sistemasweb.taquarituba.sp.gov.br',
    'https://sistemasweb.taquarituba.sp.gov.br:9445',
]


# Application definition

INSTALLED_APPS = [
    'daphne',
    'core',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.roteador_teste.UsuarioMiddleware', # Roteador de Teste
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

X_FRAME_OPTIONS = 'SAMEORIGIN'

ROOT_URLCONF = 'configuracao.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'configuracao.wsgi.application'
ASGI_APPLICATION = 'configuracao.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'conversor_afd_db',
        'USER': 'adminvm',
        'PASSWORD': '@Xj3xxyr4cjtqd6j',
        'HOST': 'localhost',
        'PORT': '3306',
    },
    'banco_teste': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'conversor_afd_teste_db',
        'USER': 'adminvm',
        'PASSWORD': '@Xj3xxyr4cjtqd6j',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}

DATABASE_ROUTERS = ['core.roteador_teste.RoteadorApresentacao']


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True


# Arquivos Estáticos (CSS, JavaScript, Images)
STATIC_URL = 'static/'
# Pasta onde o Django vai reunir todos os arquivos estáticos para o Nginx usar
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/login/'
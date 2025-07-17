from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'
    verbose_name = 'Gestión de Usuarios'

    def ready(self):
        """Ejecutar cuando la app esté lista"""
        # Importar signals si los necesitas en el futuro
        # import usuarios.signals
        pass
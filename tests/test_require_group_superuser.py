# -*- coding: utf-8 -*-
"""
test_require_group_superuser.py — Suite para require_group con superusuario (Sprint 4).
"""
import pytest
from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.core.rbac import require_group


# ─────────────────────────────────────────────────────────────────────────────
# Helper: vista decorada simple
# ─────────────────────────────────────────────────────────────────────────────

def _vista_protegida(grupos):
    """Devuelve una view decorada con require_group(*grupos) que retorna True."""
    @require_group(*grupos)
    def vista(request):
        return True
    return vista


def _make_request(user):
    """Crea un request fake con el usuario dado."""
    factory = RequestFactory()
    request = factory.get('/')
    request.user = user
    return request


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_superusuario_pasa_sin_grupo(db):
    """
    Un usuario con is_superuser=True debe pasar require_group sin pertenecer
    a ningún grupo requerido.
    """
    superuser = User.objects.create_user(
        username='super_test', password='x', is_superuser=True
    )
    vista = _vista_protegida(['Master', 'Administrador'])
    request = _make_request(superuser)

    result = vista(request)
    assert result is True, 'Superusuario debe pasar sin grupo'


@pytest.mark.django_db
def test_usuario_sin_grupo_bloqueado(db):
    """
    Un usuario sin grupos (y sin is_superuser) debe recibir PermissionDenied.
    """
    user = User.objects.create_user(username='sin_grupo', password='x')
    vista = _vista_protegida(['Master'])
    request = _make_request(user)

    with pytest.raises(PermissionDenied):
        vista(request)


@pytest.mark.django_db
def test_usuario_con_grupo_correcto_pasa(db):
    """
    Un usuario que pertenece al grupo requerido debe pasar sin PermissionDenied.
    """
    grupo, _ = Group.objects.get_or_create(name='Administrador')
    user = User.objects.create_user(username='user_admin_test', password='x')
    user.groups.add(grupo)

    vista = _vista_protegida(['Administrador'])
    request = _make_request(user)

    result = vista(request)
    assert result is True, 'Usuario en grupo correcto debe pasar'

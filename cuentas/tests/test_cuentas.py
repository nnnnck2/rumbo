"""RF-30 (SCRUM-27) y RF-11 (SCRUM-25) sin base: permisos por rol, formularios y servicios simulados."""
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from cuentas import servicios
from cuentas.forms import UsuarioForm
from cuentas.permisos import ADMIN, SUPERVISION, TODOS, con_rol
from leads.servicios import Contexto, ErrorNegocio


def _vista(*roles):
    return con_rol(*roles)(lambda request: HttpResponse("ok"))


class PermisosTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _pedir(self, roles, rol):
        request = self.rf.get("/x/")
        request.user = mock.Mock(is_authenticated=True)
        with mock.patch("cuentas.permisos.servicios.contexto_actual", return_value=Contexto(5, rol, None)):
            return _vista(*roles)(request)

    def test_sin_sesion_va_al_login(self):
        request = self.rf.get("/leads/")
        request.user = AnonymousUser()
        r = _vista(*TODOS)(request)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cuentas/ingresar/", r["Location"])

    def test_matriz_de_roles(self):
        casos = [(TODOS, "asesor", True), (SUPERVISION, "asesor", False), (SUPERVISION, "supervisor", True),
                 (ADMIN, "supervisor", False), (ADMIN, "admin", True), (TODOS, None, False)]
        for roles, rol, permitido in casos:
            with self.subTest(roles=roles, rol=rol):
                if permitido:
                    self.assertEqual(self._pedir(roles, rol).status_code, 200)
                else:
                    with self.assertRaises(PermissionDenied):
                        self._pedir(roles, rol)


class EstadoAsesorTests(SimpleTestCase):
    def test_estado_no_elegible(self):
        with self.assertRaises(ErrorNegocio):
            servicios.cambiar_estado("ocupado")

    def test_usa_la_funcion_de_la_base(self):
        with mock.patch.object(servicios, "_sql") as sql:
            servicios.cambiar_estado("pausa", 7)
        self.assertIn("rumbo.cambiar_estado_asesor", sql.call_args.args[0])
        self.assertEqual(sql.call_args.args[1], ["pausa", 7])


class ActualizarUsuarioTests(SimpleTestCase):
    def _actualizar(self, rol_actual, **kw):
        user = mock.Mock(pk=9)
        perfil = mock.Mock(rol=rol_actual)
        with mock.patch.object(servicios.Usuario.objects, "filter") as f:
            f.return_value.first.return_value = perfil
            servicios.actualizar_usuario(user, nombre="X", **kw)

    def test_asesor_no_cambia_de_rol(self):
        with self.assertRaisesMessage(ErrorNegocio, "no puede cambiar de rol"):
            self._actualizar("asesor", rol="supervisor", activo=True)

    def test_admin_no_se_desactiva_a_si_mismo(self):
        with self.assertRaisesMessage(ErrorNegocio, "a sí mismo"):
            self._actualizar("admin", rol="admin", activo=False, editor_id=9)


class UsuarioFormTests(SimpleTestCase):
    datos = {"username": "ana.perez", "nombre": "Ana Pérez", "rol": "asesor",
             "password1": "Visas-Rumbo-2026!", "password2": "Visas-Rumbo-2026!"}

    def _form(self, datos, **kw):
        with mock.patch("cuentas.forms.get_user_model") as gum, mock.patch("cuentas.forms.Asesor") as asesor:
            gum.return_value.objects.filter.return_value.exists.return_value = False
            gum.return_value.side_effect = lambda **k: mock.Mock(**k, _meta=mock.Mock())
            asesor.objects.filter.return_value.exists.return_value = False
            form = UsuarioForm(datos, **kw)
            form.fields["numero_whatsapp"].queryset = mock.MagicMock()
            form.is_valid()
        return form

    def test_alta_exige_contrasena(self):
        f = self._form(self.datos | {"password1": "", "password2": ""})
        self.assertIn("password1", f.errors)

    def test_contrasenas_distintas(self):
        f = self._form(self.datos | {"password2": "otra-cosa-larga-1"})
        self.assertIn("password2", f.errors)

    def test_contrasena_debil(self):
        f = self._form(self.datos | {"password1": "12345678", "password2": "12345678"})
        self.assertIn("password1", f.errors)

    def test_datos_para_el_servicio(self):
        f = self._form(self.datos | {"codigo_callflow": " EMP-1 "})
        self.assertTrue(f.is_valid(), f.errors)
        d = f.datos_servicio()
        self.assertEqual((d["rol"], d["codigo_callflow"], d["password"]), ("asesor", "EMP-1", "Visas-Rumbo-2026!"))

    def test_supervisor_no_lleva_datos_de_asesor(self):
        f = self._form(self.datos | {"rol": "supervisor", "codigo_callflow": "EMP-1"})
        self.assertIsNone(f.datos_servicio()["codigo_callflow"])

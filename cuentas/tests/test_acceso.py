"""SCRUM-35 sin base: contraseñas robustas, IP del cliente, bloqueo en el login y auditoría solo para admin.
La parte de base (registro inmutable y cálculo del bloqueo) está en db/pruebas/12_seguridad_acceso.sql."""
import datetime as dt
from unittest import mock

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, override_settings

from cuentas import acceso
from cuentas.forms import LoginForm

AHORA = dt.datetime(2026, 11, 23, 15, 0, tzinfo=dt.timezone.utc)


class ComplejidadTests(SimpleTestCase):
    def test_rechaza_contrasenas_simples(self):
        for clave in ("solamenteletras", "1234567890123", "minusculas123"):
            with self.subTest(clave=clave), self.assertRaises(ValidationError):
                acceso.ComplejidadValidator().validate(clave)

    def test_acepta_robustas(self):
        for clave in ("Visas-Rumbo-2026!", "Multivisa2026x!", "OtraClave2026"):
            with self.subTest(clave=clave):
                acceso.ComplejidadValidator().validate(clave)

    def test_esta_en_los_validadores_del_proyecto(self):
        nombres = [type(v).__name__ for v in password_validation.get_default_password_validators()]
        self.assertIn("ComplejidadValidator", nombres)
        self.assertIn("MinimumLengthValidator", nombres)


class IpClienteTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_en_desarrollo_usa_remote_addr_e_ignora_x_real_ip(self):
        r = self.rf.get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_REAL_IP="1.2.3.4")
        self.assertEqual(acceso.ip_cliente(r), "10.0.0.5")

    @override_settings(RUMBO_CONFIAR_X_REAL_IP=True)
    def test_detras_de_nginx_usa_x_real_ip(self):
        r = self.rf.get("/", REMOTE_ADDR="172.18.0.2", HTTP_X_REAL_IP="190.10.20.30")
        self.assertEqual(acceso.ip_cliente(r), "190.10.20.30")

    @override_settings(RUMBO_CONFIAR_X_REAL_IP=True)
    def test_ip_invalida_cae_a_remote_addr(self):
        r = self.rf.get("/", REMOTE_ADDR="172.18.0.2", HTTP_X_REAL_IP="no-es-ip")
        self.assertEqual(acceso.ip_cliente(r), "172.18.0.2")


class TextoEsperaTests(SimpleTestCase):
    def test_redondea_hacia_arriba(self):
        self.assertEqual(acceso.texto_espera(AHORA + dt.timedelta(minutes=14, seconds=5), AHORA), "15 minutos")
        self.assertEqual(acceso.texto_espera(AHORA + dt.timedelta(seconds=20), AHORA), "1 minuto")


class LoginBloqueadoTests(SimpleTestCase):
    def test_bloqueado_no_comprueba_la_contrasena(self):
        request = RequestFactory().post("/cuentas/ingresar/")
        form = LoginForm(request, data={"username": "ana", "password": "la-correcta"})
        hasta = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        with mock.patch.object(acceso, "bloqueado_hasta", return_value=hasta), \
             mock.patch.object(acceso, "registrar") as registrar, \
             mock.patch("cuentas.forms.get_user_model") as modelo, \
             mock.patch("django.contrib.auth.forms.authenticate") as autenticar:
            modelo.return_value.objects.filter.return_value.values_list.return_value.first.return_value = 7
            self.assertFalse(form.is_valid())
        autenticar.assert_not_called()
        registrar.assert_called_once_with(request, "ana", "bloqueado", 7)
        self.assertIn("espere 10 minutos", form.non_field_errors()[0])

    def test_sin_bloqueo_autentica_normal(self):
        request = RequestFactory().post("/cuentas/ingresar/")
        form = LoginForm(request, data={"username": "ana", "password": "mal"})
        with mock.patch.object(acceso, "bloqueado_hasta", return_value=None), \
             mock.patch("django.contrib.auth.forms.authenticate", return_value=None) as autenticar:
            self.assertFalse(form.is_valid())
        autenticar.assert_called_once()
        self.assertIn("incorrectos", form.non_field_errors()[0])


class CargaAsesorFormTests(SimpleTestCase):
    """SCRUM-54 · Límite de pendientes y parte del reparto en el formulario de usuario."""

    def _form(self, **extra):
        from cuentas.forms import UsuarioForm

        datos = {"username": "nuevo1", "nombre": "Nuevo", "rol": "asesor", "password1": "Visas-Rumbo-2026!",
                 "password2": "Visas-Rumbo-2026!"} | extra
        with mock.patch("cuentas.forms.get_user_model") as modelo, mock.patch("cuentas.forms.Asesor"):
            modelo.return_value.objects.filter.return_value.exists.return_value = False
            modelo.return_value.side_effect = None
            form = UsuarioForm(data=datos)
            form.fields["numero_whatsapp"].queryset = mock.MagicMock()
            form.is_valid()
        return form

    def test_por_defecto_sin_limite_y_peso_completo(self):
        from decimal import Decimal

        self.assertEqual(self._form().datos_carga(), (None, Decimal("1.00")))

    def test_limite_y_medio_peso(self):
        from decimal import Decimal

        self.assertEqual(self._form(max_pendientes="5", peso_reparto="0.50").datos_carga(), (5, Decimal("0.50")))

    def test_limite_fuera_de_rango(self):
        self.assertIn("max_pendientes", self._form(max_pendientes="0").errors)
        self.assertIn("peso_reparto", self._form(peso_reparto="0.05").errors)

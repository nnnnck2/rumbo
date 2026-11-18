"""RF-02 · firma válida e inválida."""
from django.test import SimpleTestCase

from whatsapp.firma import calcular_firma, verificar_firma

SECRETO = "secreto-de-prueba"
CUERPO = b'{"object":"whatsapp_business_account","entry":[]}'


class FirmaTests(SimpleTestCase):
    def test_firma_valida(self):
        self.assertEqual(verificar_firma(CUERPO, calcular_firma(CUERPO, SECRETO), SECRETO), (True, "ok"))

    def test_firma_en_mayusculas_es_valida(self):
        self.assertTrue(verificar_firma(CUERPO, calcular_firma(CUERPO, SECRETO).upper().replace("SHA256=", "sha256="), SECRETO)[0])

    def test_firma_de_otro_secreto(self):
        self.assertEqual(verificar_firma(CUERPO, calcular_firma(CUERPO, "otro"), SECRETO), (False, "firma inválida"))

    def test_cuerpo_alterado(self):
        firma = calcular_firma(CUERPO, SECRETO)
        self.assertFalse(verificar_firma(CUERPO + b" ", firma, SECRETO)[0])

    def test_sin_cabecera(self):
        self.assertEqual(verificar_firma(CUERPO, None, SECRETO), (False, "sin cabecera X-Hub-Signature-256"))

    def test_formato_desconocido(self):
        self.assertFalse(verificar_firma(CUERPO, "sha1=abc", SECRETO)[0])

    def test_caracteres_no_ascii(self):
        self.assertFalse(verificar_firma(CUERPO, "sha256=ñ", SECRETO)[0])

    def test_sin_secreto_rechaza_todo(self):
        self.assertFalse(verificar_firma(CUERPO, calcular_firma(CUERPO, ""), "")[0])

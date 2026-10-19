"""Motor de Document AI: PRE-CONFIGURADO pero sin activar.

Para activarlo cuando la evaluación con Gemini lo justifique:
  1. Entrenar un Custom Extractor y/o Custom Classifier en Document AI.
  2. Definir DOCAI_LOCATION y un DOCAI_PROCESSOR_<TIPO> por tipo (p. ej. DOCAI_PROCESSOR_CURP).
  3. Implementar `analizar` y `clasificar` devolviendo el mismo contrato que motor_gemini.py
     (los 'checks' visuales, como logos o QR, seguirían viniendo de Gemini y del código).
  4. Elegir el motor por tarea en validar.py (variables MOTOR_CLASIFICACION / MOTOR_EXTRACCION).
"""
import os

DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "us")


def procesador(tipo: str) -> str | None:
    return os.environ.get(f"DOCAI_PROCESSOR_{tipo.upper()}")


def disponible(tipo: str) -> bool:
    return procesador(tipo) is not None


def clasificar(contents: bytes, mime: str) -> str:
    raise NotImplementedError("Motor Document AI aún no implementado")


def analizar(contents: bytes, mime: str, tipo: str) -> dict:
    raise NotImplementedError("Motor Document AI aún no implementado")

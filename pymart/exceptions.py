"""Exceptions du projet.

Chaque erreur peut contenir le nom du fichier et le numéro de ligne
pour faciliter le diagnostic des données importées.
"""
import os


class PyMartError(Exception):
    """Classe de base pour toutes les erreurs PyMart."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.file = None
        self.line = None

    def add_context(self, file=None, line=None):
        """Ajoute le contexte fichier/ligne pour faciliter le debug.

        Cette méthode est utilisée lors des erreurs de parsing pour indiquer
        précisément où le problème a été détecté dans le fichier importé.
        """
        self.file = os.path.basename(file) if file else None
        self.line = line
        return self

    def __str__(self):
        if self.file and self.line:
            return f"{self.file}:{self.line}: {self.message}"
        if self.file:
            return f"{self.file}: {self.message}"
        return self.message


class FileAccessError(PyMartError):
    """A file or directory cannot be read, written or created."""


class RecordFormatError(PyMartError):
    """A record is malformed (bad number, bad date, bad identifier...)."""


class DataValidationError(RecordFormatError):
    """A record is well formed but breaks a business rule."""


class DuplicateIdError(DataValidationError):
    """An identifier appears more than once."""


class UnknownProductError(DataValidationError):
    """A record references a product that does not exist."""


class UnknownCustomerError(DataValidationError):
    """A record references a customer that does not exist."""


class InsufficientStockError(PyMartError):
    """Not enough stock to fulfil an order line."""

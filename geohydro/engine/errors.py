"""Exception hierarchy for the engine and project layers."""


class GeoHydroError(Exception):
    """Base class for all GeoHydro Pro errors that should be shown to a user."""


class DataReadError(GeoHydroError):
    """A source file could not be read or parsed."""


class ColumnMappingError(GeoHydroError):
    """The X/Y/Z column selection is missing or inconsistent."""


class CRSError(GeoHydroError):
    """A coordinate reference system definition is invalid."""


class UnitError(GeoHydroError):
    """An unknown or incompatible measurement unit was requested."""


class ProjectFormatError(GeoHydroError):
    """A project file is not a valid GeoHydro Pro project or is unsupported."""


class ProjectIntegrityError(GeoHydroError):
    """Stored data failed an integrity (checksum) verification."""


class ProjectConflictError(GeoHydroError):
    """Saving would replace newer data on disk; explicit confirmation needed."""


class ProjectOverwriteError(GeoHydroError):
    """The target file belongs to a different project; confirmation needed."""

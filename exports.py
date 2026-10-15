"""Spreadsheet-safe text cells shared by native and browser editions."""


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value

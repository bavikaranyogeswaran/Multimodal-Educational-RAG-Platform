"""Tests for reading a raw cell grid into headers, units and data rows.

Every rule under test is a guess about a document nobody can ask, so these cases are
written around the ways a real textbook table differs from a tidy one: wrapped cells,
missing cells, units set out on their own row, a column the typesetter left unnamed,
and a table of words with no numbers anywhere to contrast against.
"""

from __future__ import annotations

from app.domain.documents.table_structure import resolve_table_structure


class TestEmptyInput:
    def test_an_empty_grid_reads_as_nothing(self) -> None:
        assert resolve_table_structure([]) is None

    def test_a_grid_of_blank_cells_reads_as_nothing(self) -> None:
        assert resolve_table_structure([["", "  "], [None, ""]]) is None

    def test_a_detected_region_with_no_text_is_not_an_empty_table(self) -> None:
        # The distinction matters: returning a one-column table here would put a table
        # into the index that the document does not contain.
        assert resolve_table_structure([[None, None, None]]) is None


class TestHeaderDetection:
    def test_a_row_of_words_above_numbers_is_the_header(self) -> None:
        result = resolve_table_structure(
            [["Metal", "Density"], ["Aluminium", "2.70"], ["Iron", "7.87"]]
        )
        assert result is not None
        assert result.headers == ("Metal", "Density")
        assert result.header_assumed is False
        assert result.rows == (("Aluminium", "2.70"), ("Iron", "7.87"))

    def test_a_row_carrying_numbers_is_not_spent_as_a_header(self) -> None:
        result = resolve_table_structure([["1", "2.70"], ["2", "7.87"]])
        assert result is not None
        assert result.header_assumed is True
        # The columns are named by position and every row survives as data. Consuming
        # the first row here would delete a row of measurements to obtain column names
        # that are themselves measurements.
        assert result.headers == ("Column 1", "Column 2")
        assert result.rows == (("1", "2.70"), ("2", "7.87"))

    def test_a_table_of_words_throughout_reads_its_first_row_as_a_header(self) -> None:
        result = resolve_table_structure(
            [["Term", "Meaning"], ["Vector", "A quantity with direction"]]
        )
        assert result is not None
        assert result.headers == ("Term", "Meaning")
        # Right for a glossary, but reached by convention rather than evidence, so the
        # flag says so.
        assert result.header_assumed is True
        assert result.rows == (("Vector", "A quantity with direction"),)

    def test_a_headerless_numeric_table_keeps_every_row(self) -> None:
        result = resolve_table_structure([["1", "2"], ["3", "4"], ["5", "6"]])
        assert result is not None
        assert len(result.rows) == 3


class TestUnits:
    def test_a_parenthesised_unit_is_split_from_the_column_name(self) -> None:
        result = resolve_table_structure([["Mass (kg)", "Length (m)"], ["2.70", "1.5"]])
        assert result is not None
        assert result.headers == ("Mass", "Length")
        assert result.units == ("kg", "m")

    def test_a_bracketed_unit_is_split_the_same_way(self) -> None:
        result = resolve_table_structure([["Speed [m/s]"], ["9.81"]])
        assert result is not None
        assert result.headers == ("Speed",)
        assert result.units == ("m/s",)

    def test_a_dedicated_units_row_is_read_as_units(self) -> None:
        result = resolve_table_structure(
            [["Metal", "Density"], ["", "g/cm3"], ["Aluminium", "2.70"]]
        )
        assert result is not None
        assert result.headers == ("Metal", "Density")
        assert result.units == (None, "g/cm3")
        # The units row is consumed, not left sitting in the data.
        assert result.rows == (("Aluminium", "2.70"),)

    def test_a_units_row_with_nothing_numeric_below_stays_data(self) -> None:
        # Without measurements underneath it, a terse second row is a second header
        # rather than units, and taking it would discard a row of content.
        result = resolve_table_structure([["Term", "Symbol"], ["Mass", "m"], ["Time", "t"]])
        assert result is not None
        assert result.units == (None, None)
        assert ("Mass", "m") in result.rows

    def test_a_dedicated_units_row_wins_over_one_in_the_header(self) -> None:
        result = resolve_table_structure(
            [["Mass (lb)"], ["kg"], ["2.70"]],
        )
        assert result is not None
        assert result.units == ("kg",)

    def test_a_whole_heading_in_parentheses_is_a_name_not_a_unit(self) -> None:
        result = resolve_table_structure([["(estimated)"], ["2.70"]])
        assert result is not None
        assert result.headers == ("(estimated)",)
        assert result.units == (None,)

    def test_a_column_with_no_unit_reports_none(self) -> None:
        result = resolve_table_structure([["Metal", "Density (g/cm3)"], ["Iron", "7.87"]])
        assert result is not None
        assert result.units == (None, "g/cm3")


class TestRaggedRows:
    def test_a_short_row_is_padded_and_reported(self) -> None:
        result = resolve_table_structure([["A", "B", "C"], ["1", "2"]])
        assert result is not None
        assert result.was_ragged is True
        assert result.rows == (("1", "2", ""),)

    def test_a_row_wider_than_its_header_widens_the_table(self) -> None:
        result = resolve_table_structure([["A", "B"], ["1", "2", "3"]])
        assert result is not None
        assert result.was_ragged is True
        # Width comes from the widest row, so the header is what gets padded, and the
        # extra column is named by position rather than dropped along with its value.
        assert len(result.headers) == 3
        assert result.headers[2] == "Column 3"
        assert result.rows == (("1", "2", "3"),)

    def test_a_square_grid_is_not_reported_as_ragged(self) -> None:
        result = resolve_table_structure([["A", "B"], ["1", "2"]])
        assert result is not None
        assert result.was_ragged is False

    def test_every_row_ends_up_the_width_of_the_headers(self) -> None:
        result = resolve_table_structure([["A", "B", "C"], ["1"], ["1", "2", "3", "4"]])
        assert result is not None
        width = len(result.headers)
        assert all(len(row) == width for row in result.rows)


class TestCellCleaning:
    def test_a_wrapped_cell_is_joined_onto_one_line(self) -> None:
        result = resolve_table_structure([["Tensile\nstrength"], ["410"]])
        assert result is not None
        assert result.headers == ("Tensile strength",)

    def test_surrounding_whitespace_is_removed(self) -> None:
        result = resolve_table_structure([["  Metal  "], ["  Iron  "]])
        assert result is not None
        assert result.headers == ("Metal",)
        assert result.rows == (("Iron",),)

    def test_a_none_cell_becomes_empty_rather_than_the_word_none(self) -> None:
        result = resolve_table_structure([["A", "B"], ["1", None]])
        assert result is not None
        assert result.rows == (("1", ""),)


class TestUnnamedColumns:
    def test_a_blank_column_name_is_numbered_by_position(self) -> None:
        result = resolve_table_structure([["Metal", ""], ["Iron", "7.87"]])
        assert result is not None
        assert result.headers == ("Metal", "Column 2")

    def test_numbering_is_one_based_to_match_how_a_reader_counts(self) -> None:
        result = resolve_table_structure([["", ""], ["a", "1"]])
        assert result is not None
        assert result.headers == ("Column 1", "Column 2")


class TestNumericRecognition:
    def test_a_thousands_separator_still_reads_as_a_number(self) -> None:
        result = resolve_table_structure([["City", "Population"], ["Lisbon", "544,851"]])
        assert result is not None
        assert result.header_assumed is False

    def test_a_measurement_with_a_comparison_prefix_reads_as_a_number(self) -> None:
        result = resolve_table_structure([["Sample", "Error"], ["A", "<0.01"]])
        assert result is not None
        assert result.header_assumed is False

    def test_a_negative_value_reads_as_a_number(self) -> None:
        result = resolve_table_structure([["Point", "Temperature"], ["Freezing", "-40.5"]])
        assert result is not None
        assert result.header_assumed is False

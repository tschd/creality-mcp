from pathlib import Path

from creality_mcp.gcode import parse_duration, parse_gcode

GCODE = Path(__file__).parent / "fixtures" / "gcode"


def test_creality_k2():
    s = parse_gcode(GCODE / "creality_k2.gcode")
    assert s.plate == 1
    assert s.print_time_text == "12m 30s"
    assert s.print_time_s == 750
    assert s.filament_g == [4.34]
    assert s.filament_mm == [1454.2]
    assert s.layers == 100
    assert s.settings["printer_model"] == "Creality K2 Plus"
    assert s.settings["printer_settings_id"] == "Creality K2 Plus 0.4 nozzle"
    assert s.settings["print_settings_id"] == "0.20mm Standard @Creality K2 Plus 0.4 nozzle"
    assert s.settings["layer_height"] == "0.2"
    assert s.missing == []
    assert s.warning is None


def test_bbl_x1c():
    s = parse_gcode(GCODE / "bbl_x1c.gcode", plate=2)
    assert s.plate == 2
    assert s.print_time_text == "10m 22s"
    assert s.print_time_s == 622
    assert s.filament_mm == [1292.49]
    assert s.filament_g is None
    assert s.missing == ["filament_g"]
    assert s.layers == 100


def test_two_filaments():
    s = parse_gcode(GCODE / "two_filament.gcode")
    assert s.filament_mm == [7365.56, 9265.95]
    assert s.filament_g == [21.97, 27.86]
    assert s.print_time_s == 11713
    assert s.settings["filament_settings_id"] == (
        '"Hyper PLA @Creality K2 Plus 0.4 nozzle";"CR-PLA @Creality K2 Plus 0.4 nozzle"'
    )


def test_parse_duration():
    assert parse_duration("1h 2m 3s") == 3723
    assert parse_duration("45s") == 45
    assert parse_duration("22m 25s") == 1345
    assert parse_duration("1d 2h 3m 4s") == 93784
    assert parse_duration("n/a") is None
    assert parse_duration("") is None


def test_empty_file(tmp_path):
    empty = tmp_path / "plate_1.gcode"
    empty.write_text("")
    s = parse_gcode(empty)
    assert s.print_time_s is None
    assert s.filament_g is None
    assert s.layers is None
    assert s.missing == ["filament_g", "filament_mm", "layers", "print_time_s"]
    assert s.gcode_path == str(empty)


def test_footer_beats_earlier_body_comment(tmp_path):
    # Custom start G-code can carry a comment that looks like a stat; the footer wins.
    body = "; filament used [g] = 0\n; layer_height = 9\nG1 X0\n"
    path = tmp_path / "plate_1.gcode"
    path.write_text(body + (GCODE / "creality_k2.gcode").read_text())
    s = parse_gcode(path)
    assert s.filament_g == [4.34]
    assert s.settings["layer_height"] == "0.2"

from pandora_tui.visualizer import spectrum_lines


def test_spectrum_is_silent_without_audio_and_fits_small_sizes():
    assert spectrum_lines(bytes(48),60,3)==[' '*60]*3
    for width in (1,15,60,100):
        lines=spectrum_lines(bytes([0,128,255])*16,width,4)
        assert len(lines)==4 and all(len(line)==width for line in lines)
    assert spectrum_lines(bytes(48),0,3)==[]


def test_spectrum_uses_actual_amplitude():
    assert spectrum_lines(bytes([255]),1,3)==['█','█','█']
    assert spectrum_lines(bytes([128]),1,2)==[' ','█']

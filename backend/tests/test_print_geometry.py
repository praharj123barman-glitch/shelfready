from checker.checks.print_checks import _crosses
from checker.models import BBox

BOX = BBox(x0=100, y0=100, x1=200, y1=120)


def test_fold_through_the_text_counts():
    assert _crosses((150, 0, 150, 500), BOX)  # vertical fold through the middle
    assert _crosses((0, 110, 500, 110), BOX)  # horizontal fold through the middle


def test_fold_touching_the_edge_does_not_count():
    assert not _crosses((100.5, 0, 100.5, 500), BOX)  # within the 1 pt tolerance
    assert not _crosses((0, 130, 500, 130), BOX)  # passes below


def test_diagonal_dust_flap_fold():
    assert _crosses((90, 90, 210, 130), BOX)
    assert not _crosses((0, 0, 50, 300), BOX)

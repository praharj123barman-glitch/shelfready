import pytest

from checker.nutrition import atwater_calories, expected_dv, expected_rounding


@pytest.mark.parametrize(
    "key, amount, expected",
    [
        ("calories", 166, 170),  # above 50: nearest 10
        ("calories", 43, 45),  # up to 50: nearest 5
        ("calories", 4, 0),
        ("total_fat", 4.3, 4.5),  # below 5 g: nearest 0.5
        ("total_fat", 15, 15),
        ("sodium", 23, 25),  # 5 to 140 mg: nearest 5
        ("sodium", 236, 240),  # above 140: nearest 10
        ("potassium", 23, 25),
        ("cholesterol", 45, 45),
        ("cholesterol", 4, None),  # 2 to 5 mg must read "less than 5mg"
        ("protein", 0.7, None),  # below 1 g: "less than 1g"
        ("protein", 34, 34),
    ],
)
def test_fda_rounding(key, amount, expected):
    assert expected_rounding(key, amount) == expected


@pytest.mark.parametrize(
    "key, amount, expected",
    [
        ("total_fat", 15, 19),  # 15/78 = 19.2%
        ("saturated_fat", 5, 25),
        ("sodium", 23, 1),
        ("vitamin_d", 89, 450),  # 445% -> nearest 10 above 50
        ("calcium", 206, 15),  # 15.8% -> nearest 5 between 10 and 50
        ("iron", 1, 6),  # 5.6% -> nearest 2 up to 10
        ("trans_fat", 8, None),  # no daily value
    ],
)
def test_daily_value(key, amount, expected):
    assert expected_dv(key, amount) == expected


def test_atwater():
    assert atwater_calories(fat_g=15, carb_g=66, protein_g=34) == 535

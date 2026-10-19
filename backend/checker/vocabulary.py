"""Domain word lists used by the checks, kept in one place.

Each value is a regular expression matched case-insensitively against single
ingredient items or label text. To teach the checker a new sweetener or
allergen, edit it here; every check that needs it picks it up.
"""

# ingredients that are, or contain, added sugars (US 21 CFR 101.9(c)(6)(iii), FSSAI claims regulation)
SUGAR_WORDS = r"\b(honey|sugars?|syrup|molasses|agave|dextrose|sucrose|glucose|fructose|nectar|juice concentrate)\b"

# ingredients of animal origin (vegan claims)
ANIMAL_WORDS = r"\b(honey|milk|whey|casein|lactose|butter|cream|eggs?|gelatin|beeswax|carmine|shellac|fish|anchov\w*)\b"

# US major food allergens by food source name (FD&C Act 403(w)). Coconut is not listed:
# FDA no longer treats it as a tree nut (2025 guidance), and "coconut sugar" would misfire.
US_ALLERGENS = {
    "tree nuts": r"\b(almonds?|pecans?|walnuts?|brazil nuts?|cashews?|hazelnuts?|macadamias?|pistachios?|pine nuts?)\b",
    "peanuts": r"\bpeanuts?\b",
    "milk": r"\b(milk|whey|casein|butter|cream|lactose)\b",
    "eggs": r"\beggs?\b",
    "wheat": r"\bwheat\b",
    "soybeans": r"\b(soy|soya|soybeans?)\b",
    "sesame": r"\bsesame\b",
    "fish": r"\b(fish|anchov\w*|salmon|tuna|cod)\b",
    "crustacean shellfish": r"\b(shrimp|crab|lobster|prawns?)\b",
}

# India's allergen groups (FSS Labelling and Display Regulations 2020); note that
# cereals containing gluten include oats, unlike the US list
INDIA_ALLERGENS = {
    "cereals containing gluten": r"\b(wheat|rye|barley|oats?|spelt)\b",
    "tree nuts": r"\b(almonds?|pecans?|walnuts?|brazil nuts?|cashews?|hazelnuts?|pistachios?|macadamias?)\b",
    "peanuts": r"\bpeanuts?\b",
    "milk": r"\b(milk|whey|casein|butter|cream)\b",
    "eggs": r"\beggs?\b",
    "soybeans": r"\b(soy|soya|soybeans?)\b",
    "fish": r"\bfish\b",
    "crustaceans": r"\b(shrimp|prawns?|crab|lobster)\b",
    "sulphites": r"\bsulph?ites?\b",
}

from typing import Set, Tuple

def diff_groups(old_groups: Set[str], new_groups: Set[str]) -> Tuple[Set[str], Set[str], Set[str]]:
    to_remove = old_groups - new_groups
    to_add = new_groups - old_groups
    preserved = old_groups & new_groups
    return to_remove, to_add, preserved

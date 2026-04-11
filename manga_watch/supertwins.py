from copy import deepcopy
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional


SUPERTWINS_STATE_KEY = "supertwins"
SUPERTWINS_GROUPS_KEY = "groups"
SUPERTWINS_MEMBER_IDS_KEY = "member_work_ids"
SUPERTWINS_PENDING_ACTIONS_KEY = "pending_actions"
SUPERTWINS_PENDING_SEARCHES_KEY = "pending_searches"


def ensure_supertwins_state(state: Mapping[str, object]) -> Dict[str, object]:
    updated = dict(state)
    updated[SUPERTWINS_STATE_KEY] = _normalize_supertwins_container(
        state.get(SUPERTWINS_STATE_KEY)
    )
    return updated


def create_group(
    state: Mapping[str, object],
    group_id: str,
    member_work_ids: Iterable[object],
) -> Dict[str, object]:
    normalized_group_id = _normalize_group_id(group_id)
    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    if normalized_group_id in groups:
        raise ValueError(f"supertwins group already exists: {normalized_group_id}")
    groups[normalized_group_id] = {
        SUPERTWINS_MEMBER_IDS_KEY: _normalize_member_work_ids(member_work_ids),
    }
    return _with_groups(updated, groups)


def add_group_members(
    state: Mapping[str, object],
    group_id: str,
    member_work_ids: Iterable[object],
) -> Dict[str, object]:
    normalized_group_id = _normalize_group_id(group_id)
    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    group = _copy_group(groups, normalized_group_id)
    merged_member_ids = sorted(
        set(group[SUPERTWINS_MEMBER_IDS_KEY]).union(
            _normalize_member_work_ids(member_work_ids)
        )
    )
    group[SUPERTWINS_MEMBER_IDS_KEY] = merged_member_ids
    groups[normalized_group_id] = group
    return _with_groups(updated, groups)


def remove_group_members(
    state: Mapping[str, object],
    group_id: str,
    member_work_ids: Iterable[object],
) -> Dict[str, object]:
    normalized_group_id = _normalize_group_id(group_id)
    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    group = _copy_group(groups, normalized_group_id)
    removed_member_ids = set(_normalize_member_work_ids(member_work_ids))
    group[SUPERTWINS_MEMBER_IDS_KEY] = [
        member_id
        for member_id in group[SUPERTWINS_MEMBER_IDS_KEY]
        if member_id not in removed_member_ids
    ]
    groups[normalized_group_id] = group
    return _with_groups(updated, groups)


def prune_empty_groups(state: Mapping[str, object]) -> Dict[str, object]:
    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    pruned_groups = {
        group_id: group
        for group_id, group in groups.items()
        if group[SUPERTWINS_MEMBER_IDS_KEY]
    }
    return _with_groups(updated, pruned_groups)


def prune_small_groups(state: Mapping[str, object], *, minimum_members: int = 2) -> Dict[str, object]:
    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    pruned_groups = {
        group_id: group
        for group_id, group in groups.items()
        if len(group[SUPERTWINS_MEMBER_IDS_KEY]) >= minimum_members
    }
    return _with_groups(updated, pruned_groups)


def list_groups(state: Mapping[str, object]) -> List[Dict[str, object]]:
    groups = ensure_supertwins_state(state)[SUPERTWINS_STATE_KEY][SUPERTWINS_GROUPS_KEY]
    return [
        {
            "group_id": group_id,
            SUPERTWINS_MEMBER_IDS_KEY: list(group[SUPERTWINS_MEMBER_IDS_KEY]),
        }
        for group_id, group in sorted(groups.items())
    ]


def list_group_members(state: Mapping[str, object], group_id: str) -> List[str]:
    normalized_group_id = _normalize_group_id(group_id)
    groups = ensure_supertwins_state(state)[SUPERTWINS_STATE_KEY][SUPERTWINS_GROUPS_KEY]
    if normalized_group_id not in groups:
        raise ValueError(f"supertwins group not found: {normalized_group_id}")
    return list(groups[normalized_group_id][SUPERTWINS_MEMBER_IDS_KEY])


def upsert_watchlist_entry(
    watchlist: Mapping[str, object],
    entry: Mapping[str, object],
    *,
    hidden: bool,
) -> Dict[str, object]:
    if not isinstance(watchlist, Mapping):
        raise ValueError("watchlist must be an object")
    if not isinstance(entry, Mapping):
        raise ValueError("watchlist entry must be an object")

    normalized_entry = deepcopy(dict(entry))
    work_id = str(normalized_entry.get("id") or "").strip()
    if not work_id:
        raise ValueError("watchlist entry missing id")

    works = [deepcopy(item) for item in watchlist.get("works", [])]
    existing_index = _find_watchlist_entry_index(works, work_id)
    existing: Optional[Dict[str, object]] = None
    if existing_index is None:
        normalized_entry["hidden"] = hidden
        works.append(normalized_entry)
        action = "added"
    else:
        existing = deepcopy(works[existing_index])
        merged = deepcopy(existing)
        merged.update(normalized_entry)
        merged["hidden"] = hidden
        works[existing_index] = merged
        normalized_entry = merged
        action = "duplicate"

    updated = dict(watchlist)
    updated["works"] = works
    return {
        "watchlist": updated,
        "action": action,
        "entry": deepcopy(normalized_entry),
        "existing": existing,
    }


def groups_for_member(state: Mapping[str, object], work_id: object) -> List[str]:
    normalized_work_id = str(work_id or "").strip()
    if not normalized_work_id:
        return []
    groups = ensure_supertwins_state(state)[SUPERTWINS_STATE_KEY][SUPERTWINS_GROUPS_KEY]
    return [
        group_id
        for group_id, group in sorted(groups.items())
        if normalized_work_id in group[SUPERTWINS_MEMBER_IDS_KEY]
    ]


def link_group_members(
    state: Mapping[str, object],
    member_work_ids: Iterable[object],
) -> tuple[Dict[str, object], str]:
    normalized_member_ids = _normalize_member_work_ids(member_work_ids)
    if len(normalized_member_ids) < 2:
        raise ValueError("supertwins requires at least 2 members")

    updated = ensure_supertwins_state(state)
    groups = _copy_groups(updated)
    matching_group_ids = sorted(
        {
            group_id
            for member_id in normalized_member_ids
            for group_id in groups_for_member(updated, member_id)
        }
    )
    if matching_group_ids:
        primary_group_id = matching_group_ids[0]
        merged_member_ids = set(normalized_member_ids)
        for group_id in matching_group_ids:
            merged_member_ids.update(groups[group_id][SUPERTWINS_MEMBER_IDS_KEY])
        groups[primary_group_id][SUPERTWINS_MEMBER_IDS_KEY] = sorted(merged_member_ids)
        for group_id in matching_group_ids[1:]:
            groups.pop(group_id, None)
        return _with_groups(updated, groups), primary_group_id

    group_id = _next_group_id(groups)
    groups[group_id] = {SUPERTWINS_MEMBER_IDS_KEY: normalized_member_ids}
    return _with_groups(updated, groups), group_id


def set_pending_action(
    state: Mapping[str, object],
    token: str,
    payload: Mapping[str, object],
) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise ValueError("supertwins pending action token must be a non-empty string")
    updated = ensure_supertwins_state(state)
    container = dict(updated[SUPERTWINS_STATE_KEY])
    pending_actions = dict(container.get(SUPERTWINS_PENDING_ACTIONS_KEY) or {})
    pending_actions[normalized_token] = deepcopy(dict(payload))
    container[SUPERTWINS_PENDING_ACTIONS_KEY] = pending_actions
    updated[SUPERTWINS_STATE_KEY] = container
    return updated


def get_pending_action(state: Mapping[str, object], token: str) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    container = ensure_supertwins_state(state)[SUPERTWINS_STATE_KEY]
    pending_actions = container.get(SUPERTWINS_PENDING_ACTIONS_KEY) or {}
    if not isinstance(pending_actions, Mapping):
        raise ValueError("state.supertwins.pending_actions must be an object")
    payload = pending_actions.get(normalized_token)
    if not isinstance(payload, Mapping):
        raise ValueError(f"supertwins pending action not found: {normalized_token}")
    return deepcopy(dict(payload))


def clear_pending_action(state: Mapping[str, object], token: str) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    updated = ensure_supertwins_state(state)
    container = dict(updated[SUPERTWINS_STATE_KEY])
    pending_actions = dict(container.get(SUPERTWINS_PENDING_ACTIONS_KEY) or {})
    pending_actions.pop(normalized_token, None)
    if pending_actions:
        container[SUPERTWINS_PENDING_ACTIONS_KEY] = pending_actions
    else:
        container.pop(SUPERTWINS_PENDING_ACTIONS_KEY, None)
    updated[SUPERTWINS_STATE_KEY] = container
    return updated


def set_pending_search(
    state: Mapping[str, object],
    token: str,
    payload: Mapping[str, object],
) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise ValueError("supertwins pending search token must be a non-empty string")
    updated = ensure_supertwins_state(state)
    container = dict(updated[SUPERTWINS_STATE_KEY])
    pending_searches = dict(container.get(SUPERTWINS_PENDING_SEARCHES_KEY) or {})
    pending_searches[normalized_token] = deepcopy(dict(payload))
    container[SUPERTWINS_PENDING_SEARCHES_KEY] = pending_searches
    updated[SUPERTWINS_STATE_KEY] = container
    return updated


def get_pending_search(state: Mapping[str, object], token: str) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    container = ensure_supertwins_state(state)[SUPERTWINS_STATE_KEY]
    pending_searches = container.get(SUPERTWINS_PENDING_SEARCHES_KEY) or {}
    if not isinstance(pending_searches, Mapping):
        raise ValueError("state.supertwins.pending_searches must be an object")
    payload = pending_searches.get(normalized_token)
    if not isinstance(payload, Mapping):
        raise ValueError(f"supertwins pending search not found: {normalized_token}")
    return deepcopy(dict(payload))


def clear_pending_search(state: Mapping[str, object], token: str) -> Dict[str, object]:
    normalized_token = str(token or "").strip()
    updated = ensure_supertwins_state(state)
    container = dict(updated[SUPERTWINS_STATE_KEY])
    pending_searches = dict(container.get(SUPERTWINS_PENDING_SEARCHES_KEY) or {})
    pending_searches.pop(normalized_token, None)
    if pending_searches:
        container[SUPERTWINS_PENDING_SEARCHES_KEY] = pending_searches
    else:
        container.pop(SUPERTWINS_PENDING_SEARCHES_KEY, None)
    updated[SUPERTWINS_STATE_KEY] = container
    return updated


def _with_groups(
    state: Mapping[str, object],
    groups: Mapping[str, Mapping[str, object]],
) -> Dict[str, object]:
    updated = dict(state)
    container = dict(updated[SUPERTWINS_STATE_KEY])
    container[SUPERTWINS_GROUPS_KEY] = dict(sorted(groups.items()))
    updated[SUPERTWINS_STATE_KEY] = container
    return updated


def _copy_groups(state: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    container = state[SUPERTWINS_STATE_KEY]
    groups = container[SUPERTWINS_GROUPS_KEY]
    return {group_id: deepcopy(group) for group_id, group in groups.items()}


def _copy_group(
    groups: MutableMapping[str, Dict[str, object]],
    group_id: str,
) -> Dict[str, object]:
    if group_id not in groups:
        raise ValueError(f"supertwins group not found: {group_id}")
    return deepcopy(groups[group_id])


def _find_watchlist_entry_index(
    works: Iterable[Mapping[str, object]],
    work_id: str,
) -> Optional[int]:
    for index, entry in enumerate(works):
        if str(entry.get("id")) == work_id:
            return index
    return None


def _normalize_supertwins_container(container: object) -> Dict[str, object]:
    if container is None:
        return {SUPERTWINS_GROUPS_KEY: {}}
    if not isinstance(container, Mapping):
        raise ValueError("state.supertwins must be an object")

    groups = container.get(SUPERTWINS_GROUPS_KEY, {})
    if not isinstance(groups, Mapping):
        raise ValueError("state.supertwins.groups must be an object")

    normalized = {}
    for key, value in container.items():
        if key == SUPERTWINS_GROUPS_KEY:
            continue
        if key == SUPERTWINS_PENDING_ACTIONS_KEY:
            if not isinstance(value, Mapping):
                raise ValueError("state.supertwins.pending_actions must be an object")
            normalized[key] = {str(token): deepcopy(dict(payload)) for token, payload in value.items() if isinstance(payload, Mapping)}
            continue
        if key == SUPERTWINS_PENDING_SEARCHES_KEY:
            if not isinstance(value, Mapping):
                raise ValueError("state.supertwins.pending_searches must be an object")
            normalized[key] = {
                str(token): deepcopy(dict(payload))
                for token, payload in value.items()
                if isinstance(payload, Mapping)
            }
            continue
        if value is None:
            continue
        normalized[key] = deepcopy(value)
    normalized[SUPERTWINS_GROUPS_KEY] = {
        group_id: _normalize_group_entry(group_id, entry)
        for group_id, entry in sorted(groups.items())
    }
    return normalized


def _normalize_group_entry(group_id: object, entry: object) -> Dict[str, object]:
    normalized_group_id = _normalize_group_id(group_id)
    if not isinstance(entry, Mapping):
        raise ValueError(f"state.supertwins.groups.{normalized_group_id} must be an object")

    normalized = {}
    for key, value in entry.items():
        if key == SUPERTWINS_MEMBER_IDS_KEY or value is None:
            continue
        normalized[key] = deepcopy(value)
    normalized[SUPERTWINS_MEMBER_IDS_KEY] = _normalize_member_work_ids(
        entry.get(SUPERTWINS_MEMBER_IDS_KEY, [])
    )
    return normalized


def _normalize_group_id(group_id: object) -> str:
    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        raise ValueError("supertwins group_id must be a non-empty string")
    return normalized_group_id


def _normalize_member_work_ids(member_work_ids: Iterable[object]) -> List[str]:
    if member_work_ids is None:
        return []

    normalized_member_ids = set()
    for member_work_id in member_work_ids:
        normalized_member_id = str(member_work_id or "").strip()
        if normalized_member_id:
            normalized_member_ids.add(normalized_member_id)
    return sorted(normalized_member_ids)


def _next_group_id(groups: Mapping[str, Mapping[str, object]]) -> str:
    index = 1
    while True:
        candidate = f"supertwins-{index}"
        if candidate not in groups:
            return candidate
        index += 1

"""dependency resolution for amiga packages: requires/recommends/conflicts/provides"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from emu68hatcher.data.package_loader import get_mandatory_packages, get_packages_for_version
from emu68hatcher.data.package_schema import PACKAGE_GROUPS, Package

logger = logging.getLogger(__name__)


@dataclass
class ConflictGroup:
    """a set of selected packages that cannot coexist, plus the deterministic winner."""

    token: str  # contested provides/conflicts token, or "" for a direct name conflict
    members: list[str]  # selected package names in the conflict
    chosen: str  # the package kept by deterministic resolution
    needs_user_choice: bool  # True when >=2 directly-requested picks collide (gui should ask)


@dataclass
class Resolution:
    """the outcome of resolving a requested package set."""

    selected: set[str] = field(default_factory=set)
    locked: dict[str, list[str]] = field(default_factory=dict)  # name -> requirers (greyed in gui)
    install_order: list[str] = field(default_factory=list)  # dep-before-dependent
    conflicts: list[ConflictGroup] = field(default_factory=list)  # groups worth surfacing in gui
    dropped: dict[str, str] = field(default_factory=dict)  # name -> reason (lost conflict / orphan)
    unsatisfiable: dict[str, list[str]] = field(default_factory=dict)  # token -> requirers


def _provides_of(pkg: Package) -> set[str]:
    """tokens a package satisfies: its own name plus its declared provides."""
    return {pkg.name.lower(), *(t.lower() for t in pkg.provides)}


def _group_rank(pkg: Package) -> int:
    try:
        return PACKAGE_GROUPS.index(pkg.group)
    except ValueError:
        return len(PACKAGE_GROUPS)


def resolve(
    requested: set[str],
    deselected: set[str],
    kickstart_version: str,
    emu68_version: str | None = None,
    *,
    packages: list[Package] | None = None,
    mandatory: list[Package] | None = None,
    order_hint: list[str] | None = None,
) -> Resolution:
    """resolve a user selection into a complete, conflict-free, ordered install set."""
    # deselected suppresses recommends only; packages/mandatory are injectable for tests;
    # order_hint keeps independent packages in the caller's order (deps still install first)
    requested = {n.lower() for n in requested}
    deselected = {n.lower() for n in deselected}

    if packages is None:
        packages = get_packages_for_version(kickstart_version, emu68_version)
    if mandatory is None:
        mandatory = get_mandatory_packages(kickstart_version, emu68_version)

    by_name: dict[str, Package] = {p.name.lower(): p for p in packages}
    mandatory_names = {p.name.lower() for p in mandatory}

    providers: dict[str, list[str]] = {}
    for p in packages:
        for tok in _provides_of(p):
            providers.setdefault(tok, []).append(p.name.lower())

    def pick_provider(token: str, selected: set[str], excluded: set[str]) -> str | None:
        """pick a package to satisfy a token, preferring one already selected."""
        cands = [c for c in providers.get(token, []) if c not in excluded]
        if not cands:
            return None
        # already-selected provider wins (avoids redundant/competing installs)
        for c in cands:
            if c in selected:
                return c
        # then a directly-requested one, then mandatory, then default, then stable alphabetical
        for pref in (
            lambda c: c in requested,
            lambda c: c in mandatory_names,
            lambda c: by_name[c].default,
        ):
            hit = [c for c in cands if pref(c)]
            if hit:
                return sorted(hit)[0]
        return sorted(cands)[0]

    def closure(excluded: set[str]) -> tuple[set[str], dict[str, set[str]], dict[str, list[str]]]:
        """transitive expansion over requires (hard) + recommends (soft)."""
        selected: set[str] = set()
        requirers: dict[str, set[str]] = {}
        unsat: dict[str, list[str]] = {}
        seeds = [n for n in (requested | mandatory_names) if n not in excluded]
        work = list(seeds)
        while work:
            name = work.pop()
            if name in selected or name in excluded or name not in by_name:
                continue
            selected.add(name)
            pkg = by_name[name]
            for req in pkg.requires:
                prov = pick_provider(req.lower(), selected, excluded)
                if prov is None:
                    unsat.setdefault(req.lower(), []).append(name)
                    continue
                requirers.setdefault(prov, set()).add(name)
                if prov not in selected:
                    work.append(prov)
            for rec in pkg.recommends:
                tok = rec.lower()
                if tok in deselected:
                    continue
                prov = pick_provider(tok, selected, excluded)
                if prov and prov not in selected and prov not in deselected:
                    work.append(prov)
        return selected, requirers, unsat

    def conflict_components(selected: set[str]) -> list[set[str]]:
        """connected components of mutually-conflicting selected packages (size >= 2)."""
        adj: dict[str, set[str]] = {n: set() for n in selected}
        sel_list = sorted(selected)
        prov_cache = {n: _provides_of(by_name[n]) for n in selected}
        conf_cache = {n: {t.lower() for t in by_name[n].conflicts} for n in selected}
        for i, x in enumerate(sel_list):
            for y in sel_list[i + 1 :]:
                if conf_cache[x] & prov_cache[y] or conf_cache[y] & prov_cache[x]:
                    adj[x].add(y)
                    adj[y].add(x)
        seen: set[str] = set()
        comps: list[set[str]] = []
        for n in sel_list:
            if n in seen or not adj[n]:
                continue
            stack, comp = [n], set()
            while stack:
                cur = stack.pop()
                if cur in comp:
                    continue
                comp.add(cur)
                stack.extend(adj[cur] - comp)
            seen |= comp
            comps.append(comp)
        return comps

    def shared_token(comp: set[str]) -> str:
        """a representative contested token for display (best-effort)."""
        for n in sorted(comp):
            for t in by_name[n].conflicts:
                t = t.lower()
                if any(t in _provides_of(by_name[m]) for m in comp if m != n):
                    return t
        return ""

    # fixpoint: exclude conflict losers, re-expand until stable. accumulate conflict groups
    # so one resolved in an early pass isn't lost when its losers stop re-appearing.
    excluded: set[str] = set()
    dropped: dict[str, str] = {}
    selected: set[str] = set()
    requirers: dict[str, set[str]] = {}
    unsat: dict[str, list[str]] = {}
    seen_conflicts: dict[frozenset, ConflictGroup] = {}

    for _ in range(len(packages) + 1):  # bounded; each pass excludes >=1 or stops
        selected, requirers, unsat = closure(excluded)
        new_excluded: set[str] = set()
        for comp in conflict_components(selected):
            prov_c = {n: _provides_of(by_name[n]) for n in comp}
            conf_c = {n: {t.lower() for t in by_name[n].conflicts} for n in comp}
            mand = sorted(comp & mandatory_names)
            # two pairwise-conflicting mandatory packages can't coexist. check pairwise edges,
            # not component membership, else compatible mandatory packages bridged by a third error.
            bad = next(
                (
                    (x, y)
                    for i, x in enumerate(mand)
                    for y in mand[i + 1 :]
                    if conf_c[x] & prov_c[y] or conf_c[y] & prov_c[x]
                ),
                None,
            )
            if bad:
                raise ValueError(
                    f"mandatory packages {bad[0]} and {bad[1]} conflict and cannot coexist "
                    f"(fix their provides/conflicts in the yaml)"
                )
            picks = sorted(comp & requested)
            # greedy maximal conflict-free subset: a conflict component isn't always a clique
            # (a-b, b-c, a/c ok), so keep highest-priority members, drop only those clashing a kept one.
            order = sorted(
                comp,
                key=lambda n: (
                    n not in mandatory_names,
                    n not in requested,
                    not by_name[n].default,
                    n,
                ),
            )
            kept: list[str] = []
            for n in order:
                clash = next(
                    (k for k in kept if conf_c[n] & prov_c[k] or conf_c[k] & prov_c[n]), None
                )
                if clash is not None:
                    new_excluded.add(n)
                    dropped[n] = f"conflicts with {clash}"
                else:
                    kept.append(n)
            key = frozenset(comp)
            if key not in seen_conflicts:
                seen_conflicts[key] = ConflictGroup(
                    token=shared_token(comp),
                    members=sorted(comp),
                    chosen=kept[0],
                    needs_user_choice=len(picks) >= 2 and any(p in new_excluded for p in picks),
                )
        if not (new_excluded - excluded):
            break
        excluded |= new_excluded
    else:
        logger.warning("dependency resolver hit its iteration bound; selection may be incomplete")

    conflicts = list(seen_conflicts.values())

    # locked = pulled in purely by requires (not user-picked, not mandatory) -> greyed in gui
    locked = {
        n: sorted(requirers[n])
        for n in selected
        if n not in requested and n not in mandatory_names and requirers.get(n)
    }

    install_order = _topological_order(selected, by_name, requirers, order_hint)

    return Resolution(
        selected=selected,
        locked=locked,
        install_order=install_order,
        conflicts=[c for c in conflicts if c.needs_user_choice],
        dropped=dropped,
        unsatisfiable={k: sorted(set(v)) for k, v in unsat.items()},
    )


def _topological_order(
    selected: set[str],
    by_name: dict[str, Package],
    requirers: dict[str, set[str]],
    order_hint: list[str] | None = None,
) -> list[str]:
    """kahn topo-sort on requires edges; ties by order_hint then (group, name)."""
    # edge dep -> dependent means dep installs first; in-degree counts requirers within selected
    deps: dict[str, set[str]] = {n: set() for n in selected}
    for prov, reqs in requirers.items():
        if prov not in selected:
            continue
        for r in reqs:
            if r in selected:
                deps[r].add(prov)  # r depends on prov -> prov first

    hint_idx = {n: i for i, n in enumerate(order_hint or [])}
    big = len(hint_idx)

    def rank(n: str) -> tuple[int, int, str]:
        return (hint_idx.get(n, big), _group_rank(by_name[n]), n)

    indeg = {n: len(deps[n]) for n in selected}
    ready = sorted((n for n in selected if indeg[n] == 0), key=rank)
    order: list[str] = []
    # rebuild forward adjacency: prov -> dependents
    fwd: dict[str, set[str]] = {n: set() for n in selected}
    for n in selected:
        for d in deps[n]:
            fwd[d].add(n)
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(fwd[n], key=rank):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort(key=rank)
    if len(order) != len(selected):
        # a requires-cycle: append the remainder in stable order (they co-install)
        order.extend(sorted(selected - set(order), key=rank))
    return order

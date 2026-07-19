# MudProto World Setting

This document records the shared facts and naming conventions that keep world
content coherent. It complements [story_and_world_building.md](story_and_world_building.md),
which explains the broader writing and design standard.

## Greybank

Greybank is a small fortified settlement at a river crossing. It is a place of
passage, repair, and hired work, not a capital. Carters, warders, traders, and
field hands share its gatehouse and narrow muster court. The settlement uses a
bank-and-bridge mark on public stores and arms.

The occupied settlement is only the southern gate of a larger, older keep.
Greybank controls the gatehouse, loft, muster court, and the road west. The
north barracks and bell watch are roofless in places and held by deserters. A
Cinder congregation occupies the old chapel and its undercroft to the east.
Blackwatch remains lie beneath the gatehouse and extend beyond Greybank's
present authority.

This arrangement should stay visible in room descriptions. Greybank repairs
what it uses. Uncontrolled rooms show missing roofs, improvised barricades,
stolen supplies, and fresh occupation rather than vague ruin.

## Local geography

The Lann is a shallow, stony river west of Greybank. The Lann road follows the
crossing through Briar Cut, climbs the ridge, and ends at an abandoned sheep
common. Branch paths connect the road to more distant regions.

Descriptions should preserve these relationships:

- The gatehouse opens west onto the Lann road.
- The muster court lies south of the gatehouse.
- The old keep lies north; the Cinder chapel lies east.
- The Blackwatch stair descends beneath the gatehouse.
- The river crossing, road grade, walls, and sightlines should agree in both
  directions.

## People and names

People around Greybank usually use a short given name and family name: Halda
Brakk, Marra Venn, Vessa Orr, Tarn Rusk, Bram Keld, and Ora Pell. A title belongs
in a name only when other people would actually use it in address or report.
Combat role labels belong in the UI, not in personal names.

Local place names come from use, terrain, ownership, or remembered events:
Muster Court, Ford of the Lann, Briar Cut, Bell Watch. Avoid names built from an
adjective plus a grand fantasy noun when the inhabitants would have a plainer
name.

## Magic in daily life

Magic is trained work with material traces. Wards use chalk, ash, wax, worked
metal, lamp oil, marked thresholds, and prepared stones. Healing uses clean
linen, boiled tools, salves, and spellcraft together. Descriptions should show
who maintains magic, what materials it consumes, and what residue it leaves.

Rules, costs, cooldowns, and effects remain authoritative in the attribute and
asset data. Prose must not promise a capability the mechanics do not provide.

## Content practice

- Write rooms with concrete surfaces, weather, work, damage, and evidence of
  use. Two to four focused sentences are usually enough.
- Add a `room_objects` entry when a description gives a prop enough prominence
  that a player is likely to examine it.
- Give recurring NPCs a practical concern and a restrained voice. Avoid boast
  loops, quips, and dialogue that restates a combat role.
- Keep internal IDs stable when revising presentation names. Some legacy IDs
  retain `prototype` or earlier working names because saves and references use
  them; those IDs are not player-facing canon.

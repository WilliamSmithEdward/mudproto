# Story and World-Building for High-Fantasy MUDs

**Version:** 2026-06-20
**Scope:** crafting high-fantasy worlds and narrative for text MUDs, plus tuning the
math, difficulty, and economy of their game mechanics.
**Purpose:** give an agent enforceable, independently-sourced heuristics for authoring
world content and balancing systems in a server-authoritative text MUD like MudProto.

---

## Qualification rule

A heuristic is adopted as a **hard heuristic** in this guide only when the same core
idea was independently corroborated by at least **five separately-operated publishing
organizations**. Here "independent" means five distinct publishers, not five pages of
one site, one author across venues, or reposts of the same text. This bar is stricter
than the three-source gate used by the other guides in this folder, by request.

Each heuristic lists the sources found during verification. A short
**Not yet gated** section at the end records useful ideas that did not reach five
independent sources in this pass; treat those as candidates, not rules.

This guide is about content and design, not engine code. Apply it through MudProto's
existing data-driven systems (JSON assets and config), not by inventing new ones.

---

## How an agent should use this file

Priority order when authoring world content or tuning mechanics:

1. The user's explicit task.
2. Repository instructions ([AGENTS.md](../AGENTS.md)) and the existing content/architecture
   docs ([ARCHITECTURE.md](../ARCHITECTURE.md), [ASSET_GENERATION.md](../ASSET_GENERATION.md),
   [LLM_CONTENT_GENERATION.md](../LLM_CONTENT_GENERATION.md),
   [EQUIPMENT_EFFECTS.md](../EQUIPMENT_EFFECTS.md)).
3. The hard heuristics below.
4. General craft instinct.

MudProto is server-authoritative and data-driven: world content lives in
`mudproto_server/configuration/assets/` (rooms, zones, npcs, items, gear, spells,
skills) and rules live in `mudproto_server/configuration/attributes/` (classes,
combat severity, experience, regeneration, affects, level scaling, item usage). Magic
and abilities are expressed through the centralized affect model in
`configuration/attributes/affects.json`. Tune mechanics by editing those data files,
not by special-casing logic, and keep player-facing text in clean ASCII consistent
with the display contract.

---

# Worldbuilding and setting

### WB-1. Fix the world's internal rules and keep them consistent

Define the world's internal rules (magic, physics, society) up front and apply them
without contradiction once revealed. Inner consistency, not strained suspension of
disbelief, is what earns players' secondary belief, and it matters more in a MUD,
where players relentlessly probe edge cases. Treat "never break a revealed rule" as a
strong default; rare, deliberate exceptions are survivable, gratuitous ones are not.

Sources:
- [J.R.R. Tolkien, On Fairy-Stories (Valar Guild)](https://valarguild.org/tolkien/encyc/papers/dreamlord/stages/secondary_belief.htm)
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/sandersons-first-law)
- [Quirkworthy (Jake Thornton)](https://quirkworthy.com/2020/03/03/world-building-be-consistent/)
- [Massive Entertainment (Ubisoft studio)](https://www.massive.se/blog/games-technology/ethical-worldbuilding-in-games/)
- [World Anvil](https://blog.worldanvil.com/worldanvil/interviews/how-to-create-an-rpg-system-from-scratch/)
- [Foundations of Game Design](https://gamedesigns.github.io/docs/book/chapter-01)

### WB-2. Trace a capability's consequences out to society and economy

Treat a magic system (or any powerful, widely-available capability) as real and trace
its consequences outward: derive trade, class structure, politics, law, and conflicts
from who can use it, what it costs, and what scarce resources it needs. A free, strong
capability would already have reshaped the world, so access limits must be visible at
societal scale. This both keeps the world coherent and generates plot and faction hooks.

Sources:
- [Reedsy](https://reedsy.com/blog/worldbuilding-guide/)
- [Worlds Unending](https://www.worldsunending.com/blog/economic-systems)
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/guide-to-sandersons-laws-of-magic-lecture-notes)
- [StoryFlint](https://www.storyflint.com/blog/magic-systems)
- [Fantasy Library](https://www.fantasylibrary.com/the-role-of-economy-and-trade-in-fantasy-worlds/)
- [Papers: Explorations into Children's Literature (Deakin University)](https://ojs.deakin.edu.au/index.php/pecl/article/view/2152)

### WB-3. Derive the map from physical geography and climate

Lay down physical geography and climate first using real-world climatology: place
mountain ranges, work out prevailing winds and ocean currents, route rivers downhill,
and derive rain shadows and biomes. Then place settlements, trade routes, and
resources where that terrain makes them plausible (river mouths and confluences,
passes, harbors, fertile valleys, ore-bearing ranges) so the human map follows from
cause and effect rather than arbitrary placement.

Sources:
- [Worldbuilding Workshop](https://worldbuildingworkshop.com/2015/11/27/climate/)
- [ProFantasy](https://rpgmaps.profantasy.com/world-building-how-mountains-affect-rainfall/)
- [Worldographer](https://worldographer.com/2022/11/fantasy-map-making-geography-101/)
- [Jonathan Roberts (Fantastic Maps)](https://medium.com/@jproberts00/worldbuilding-by-map-c5a55aa31fb1)
- [Anima Roleplay](https://www.anima-roleplay.com/resources/dungeon-master-toolkit/map-making-cartography/how-to-create-realistic-fantasy-maps)
- [Self-Publishing School](https://selfpublishing.com/how-to-make-a-fantasy-map/)

### WB-4. Build more than you reveal (the iceberg)

Build, or convincingly imply, far more world and history than you reveal, then surface
only a small fraction of it as specific, concrete, casually-mentioned details so the
audience infers a vast, consistent unseen depth. Withheld detail does as much work as
stated detail; over-explaining flattens the world. The hidden mass must never
contradict what is shown.

Sources:
- [Wikipedia: Impression of depth in The Lord of the Rings](https://en.wikipedia.org/wiki/Impression_of_depth_in_The_Lord_of_the_Rings)
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/worldbuilding-tools-lecture-2025)
- [Game Dev's Journey](https://gamedevsjourney.substack.com/p/the-game-devs-guide-to-worldbuilding)
- [The Iceberg Theory of Games (Aditya V)](https://adityava.medium.com/the-iceberg-theory-of-games-b12dc4a73640)
- [Obsidian Tavern](https://obsidiantavern.com/iceberg-worldbuilding/)
- [Andrea Cerasoni](https://andreacerasoni.com/blog/iceberg-method)

### WB-5. Build cultures from material conditions and history

Derive each culture's values and practices from its material conditions (climate,
terrain, resources) and its history (migrations, conquests, contact with neighbors),
then surface those forces through observable customs, dress, food, and social norms.
Draw on real cultures as raw material but hybridize several distinct influences so each
reads as original rather than a one-to-one knockoff of a single real people.

Sources:
- [Mythic Scribes](https://mythicscribes.com/world-building/worldbuilding-cultures/)
- [J.S. Morin](https://www.jsmorin.com/2014/01/creating-fictional-cultures/)
- [Runic Dice](https://www.runicdice.com/blogs/news/races-and-lineages-a-fantasy-rpg-worldbuilding-guide)
- [Help Me Naomi](https://helpmenaomi.com/creating-cultures-in-fiction/)
- [Obsidian Tavern](https://obsidiantavern.com/worldbuilding-cultures/)
- [Richie Billing](https://richiebilling.com/worldbuilding/worldbuilding-culture)

### WB-6. Give languages, names, and faiths plausible roots

Give related languages and place/character names a shared proto-language with
believable sound changes, and let religions shape daily ritual, law, and inter-group
conflict, even if only a small, consistent vocabulary and a handful of rites ever
surface in play. Consistent naming is what makes a setting feel like one place rather
than a grab-bag.

Sources:
- [Wikipedia: Languages constructed by Tolkien](https://en.wikipedia.org/wiki/Languages_constructed_by_Tolkien)
- [World Anvil Academy](https://academy.worldanvil.com/blog/worldbuilders-guide-to-fantasy-religions)
- [Mythcreants](https://mythcreants.com/blog/questions/what-should-i-avoid-while-creating-names-in-fantasy-cultures/)
- [Inkwell Ideas](https://inkwellideas.com/worldbuilding/worldbuilding-religion-design/)
- [Penguin Random House (David J. Peterson)](https://www.penguinrandomhouse.com/books/316207/the-art-of-language-invention-by-david-j-peterson/)
- [MultiLingual Magazine](https://multilingual.com/issues/october-2022/j-r-r-tolkiens-life-in-languages-inventing-and-adapting-the-lexicons-of-middle-earth/)

### WB-7. Give the world a continuous, causal history

Give the world a continuous, era-divided history in which events cause one another and
no long stretch sits empty, so the present is legibly the product of its past: ruins,
grudges, shifted borders, and lost technologies that double as quest and faction hooks.
In MudProto, encode this through zone and room lore and NPC backstory rather than
exposition dumps.

Sources:
- [World Anvil](https://academy.worldanvil.com/blog/worldbuilding-relics-and-history)
- [Richie Billing](https://richiebilling.com/worldbuilding/how-to-create-a-history-for-fantasy-world)
- [LegendKeeper](https://www.legendkeeper.com/rpg-campaign-history/)
- [The Critical Dragon](https://thecriticaldragon.com/2016/02/25/time-for-a-lack-of-change-the-passage-of-time-in-fantasyland/)
- [Lorefrog](https://lorefrog.com/blog/the-art-of-decay-ancient-echoes-in-your-worldbuilding/)
- [LitRPG Reads](https://litrpgreads.com/blog/rpg/forging-the-past-building-your-tabletop-rpg-fantasy-world-history)

---

# Magic and ability systems

In MudProto these map to spells, skills, and the shared affect model
(`configuration/attributes/affects.json`, referenced by `affect_ids`).

### MG-1. Sanderson's First Law: understanding gates resolution

An author's ability to resolve conflict satisfyingly with magic is proportional to how
well the audience understands that magic. The better players grasp the rules and
limits, the more a magical solution feels earned; resolving a conflict with an
unexplained or newly-invented power reads as a deus ex machina. Corollary: well-understood
("hard") magic can solve problems, while mysterious ("soft") magic should mainly create them.

Sources:
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/sandersons-first-law)
- [Dabble](https://www.dabblewriter.com/articles/create-magic-systems)
- [Unusual Things (Maxon)](https://maxonwriting.com/2016/08/02/being-a-better-writer-sandersons-three-laws-of-magic/)
- [Worldbuilding School](https://worldbuildingschool.com/first-law-of-magic-sanderson/)
- [Bang2Write](https://bang2write.com/2023/10/brandon-sandersons-3-laws-for-creating-magic-systems-in-your-fantasy-story.html)
- [Fantasy-Hive](https://fantasy-hive.co.uk/2019/12/a-guide-to-writing-magic-systems/)

### MG-2. Limitations over powers (Sanderson's Second Law)

Define a power's limitations, weaknesses, and costs before its raw capabilities: what
an ability cannot do and what it is vulnerable to drives more tension and cleverer play
than what it can do. The same principle is the primary lever for game balance, since
exploitable weaknesses and counterplay are what keep a strong option from becoming
mandatory.

Sources:
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/sandersons-second-law)
- [Kevin T. Johns](https://www.kevintjohns.com/how-magic-systems-create-or-destroy-tension-in-fantasy/)
- [Fantasy-Faction](https://fantasy-faction.com/2018/creating-a-magic-system)
- [September C. Fawkes](https://www.septembercfawkes.com/2016/05/sandersons-3-laws-of-magic-systems.html)
- [Quill and Steel](https://www.quillandsteel.com/blogs/writing-tips/how-to-create-a-magic-system)
- [Game Developer: Design 101, Balancing Games](https://www.gamedeveloper.com/design/design-101-balancing-games)
- [CritPoints (Celia Wagar)](https://critpoints.net/2025/05/06/building-counterplay-for-pvp-games/)

### MG-3. Attach a real, escalating cost to power

Attach a real, escalating cost to every use of magic or special power (energy, time,
materials, health, memory, relationships) so each use is a deliberate trade-off rather
than a free win. This is the same resource and opportunity-cost principle that makes
game decisions meaningful: when power is free, obstacles trivialize and tension
collapses, so the cost must be proportional to the benefit. In MudProto, model costs as
vigor/mana spend and cooldowns.

Sources:
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/sandersons-second-law)
- [Game Design Concepts (Ian Schreiber)](https://gamedesignconcepts.wordpress.com/2009/08/20/level-16-game-balance/)
- [Fantasy-Hive](https://fantasy-hive.co.uk/2019/12/a-guide-to-writing-magic-systems/)
- [Mythcreants](https://mythcreants.com/blog/four-ways-to-limit-magic-technology/)
- [Flesh and Blood TCG (Legend Story Studios)](https://fabtcg.com/articles/designer-cost-meaningful-decisions/)
- [Atsiko's Chimney](https://atsiko.wordpress.com/2010/12/08/the-real-cost-of-magic-part-1/)

### MG-4. Choose hard vs soft magic by its story role

Decide hard vs soft magic by the role magic plays, not its aesthetic: make it hard
(rules and limits the audience understands) when characters use it to resolve major
conflicts, and keep it soft (mysterious, undefined) when its job is wonder, threat, or
atmosphere, in which case it should create problems rather than solve them. Game systems
trend hard by necessity because mechanics must be codified for informed choices.

Sources:
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/sandersons-first-law)
- [EN World](https://www.enworld.org/threads/worlds-of-design-the-rules-of-magic.683548/)
- [LegendKeeper](https://www.legendkeeper.com/hard-and-soft-magic/)
- [Dabble](https://www.dabblewriter.com/articles/hard-vs-soft-magic)
- [Eric Falden](https://ericfalden.substack.com/p/why-magic-systems-matter)
- [Fabled Planet](https://fabledplanet.com/hard-versus-soft-magic-system-which-is-better-for-your-fantasy-novel/)

### MG-5. Make abilities simple, consistent rules that interact

Design the ability system as a small set of simple, consistent, player-knowable rules
that interact globally rather than via one-off scripted exceptions. Because players can
learn and predict the rules, they combine them into valid solutions the designer never
explicitly authored: this is the engine of emergent play. Constraints are essential,
not incidental, since they channel ingenuity and make clever solutions feel earned.
This matches MudProto's preference for a unified affect model over bespoke branches.

Sources:
- [Wikipedia: Immersive sim](https://en.wikipedia.org/wiki/Immersive_sim)
- [Brandon Sanderson FAQ](https://faq.brandonsanderson.com/knowledge-base/what-are-sandersons-laws-of-magic/)
- [Game Developer (Warren Spector)](https://www.gamedeveloper.com/design/spector-go-emergent---game-design-is-not-all-about-you)
- [Wizards of the Coast (Mark Rosewater)](https://magic.wizards.com/en/news/making-magic/ten-things-every-game-needs-part-1-part-2-2011-12-19)
- [TV Tropes: Immersive Sim](https://tvtropes.org/pmwiki/pmwiki.php/Main/ImmersiveSim)
- [O'Reilly: Practical Game Design](https://www.oreilly.com/library/view/practical-game-design/9781787121799/e625bb17-7be0-4634-b9c1-cb6be8aa0330.xhtml)

### MG-6. Ration power through finite, depletable resources

Constrain magic with finite, depletable resources (spell slots, mana, per-day uses,
recharge-on-rest) so each cast is a rationing decision under attrition. This caps burst
and sustained output, prevents spamming the strongest ability, and keeps low-resource
characters relevant. Calibrate to the encounter cadence: too-loose caps let casters
dominate, too-tight caps make depleted casters dead weight.

Sources:
- [Game Developer: Controlling the stream of mana](https://www.gamedeveloper.com/design/controlling-the-stream-of-mana-in-rpgs-in-order-to-empower-the-player-to-use-the-game-s-mechanics)
- [The Angry GM](https://theangrygm.com/you-dont-get-attrition/)
- [The RPG Gazette](https://therpggazette.wordpress.com/2025/07/31/what-is-fireball-an-exploration-of-vancian-magic-and-its-alternatives/)
- [DMs Workshop](https://dmsworkshop.com/2021/07/09/no-vancian-magic/)
- [Taugrim's MMO Blog](https://taugrim.com/2013/01/03/mana-bars-good-or-bad-game-design/)
- [Myers Fiction](https://myersfiction.com/2024/08/20/crafting-believable-magic-systems-with-limits-and-costs/)

---

# Narrative, quests, and lore

### NQ-1. Deliver lore incrementally, never as an info-dump

Deliver lore through player action, the environment, and incidental detail rather than
exposition blocks: show the world via what characters do and what the space reveals,
drip-feed only story-relevant pieces, and avoid the "as you know" dialogue and
history-lecture anti-patterns so plot and character stay ahead of explanation.

Sources:
- [Game Developer: Environmental storytelling](https://www.gamedeveloper.com/design/environmental-storytelling)
- [Brandon Sanderson](https://www.brandonsanderson.com/blogs/blog/worldbuilding-tools-lecture-2025)
- [IntechOpen](https://www.intechopen.com/chapters/1225186)
- [Keewano](https://keewano.com/blog/5-environmental-storytelling-techniques-every-game-writer-must-know/)
- [Pixune Studios](https://pixune.com/blog/environmental-storytelling-in-games/)
- [Mythcreants](https://mythcreants.com/blog/questions/how-can-i-work-complex-worldbuilding-into-my-story/)

### NQ-2. Let the space carry the story

Make the location itself carry the story. Compose each place from concrete detail plus
cause-and-effect aftermath evidence of prior events (broken doors, scorch marks, an
abandoned camp) so a player can answer "Where am I?" and "What happened here?" by
observation and inference, without narration. In a MUD the room description does the
immersive work that visuals do elsewhere, so make it concrete and readable.

Sources:
- [Game Developer (theme-park lessons)](https://www.gamedeveloper.com/design/environmental-storytelling-creating-immersive-3d-worlds-using-lessons-learned-from-the-theme-park-industry)
- [GDC Vault: What Happened Here](https://gdcvault.com/play/1012647/What-Happened-Here-Environmental)
- [IntechOpen](https://www.intechopen.com/chapters/1225186)
- [The Level Design Book](https://book.leveldesignbook.com/process/env-art/storytelling)
- [USC Scalar](https://scalar.usc.edu/works/interactive-storytelling-narrative-techniques-and-methods-in-video-games/environmental-storytelling)
- [Nieman Storyboard (Harvard)](https://niemanstoryboard.org/2011/01/14/harvey-smith-on-environmental-storytelling-and-embedding-narrative/)

### NQ-3. Use archetypes deliberately; cliche is mechanical use

Treat genre archetypes and tropes as deliberate, recognizable shorthand that meets
player expectations, but master them well enough to twist or recombine them. A cliche
is not the trope itself but the result of using it mechanically or letting
under-developed worldbuilding fill its gaps with borrowed material. For MudProto's
classes and races, lean on legible archetypes with grounded, specific subversions.

Sources:
- [Reedsy](https://reedsy.com/blog/fantasy-tropes/)
- [Anne R. Allen](https://annerallen.com/2022/10/tropes-and-archetypes-vs-cliches/)
- [Atmosphere Press](https://atmospherepress.com/subverting-writing-tropes/)
- [Writers Helping Writers](https://writershelpingwriters.net/2022/10/the-top-three-world-building-pitfalls-and-how-to-avoid-them/)
- [Quill and Steel](https://www.quillandsteel.com/blogs/writing-tips/common-fantasy-tropes)
- [Fictionphile](https://fictionphile.com/jungian-archetypes-character-classes/)

### NQ-4. Never ship a bare fetch or kill quest

Anchor every objective in narrative context (the world's history or an NPC the player
already knows), give it a personal stake, and add one memorable twist or complication.
Context plus stakes plus a surprise turns a mechanically identical errand into a quest
worth remembering.

Sources:
- [PCGamesN (Witcher 3 quest design)](https://www.pcgamesn.com/the-witcher-3-wild-hunt/the-witcher-quest-design-cd-projekt-masterclass)
- [Game Developer: Designing side quests](https://www.gamedeveloper.com/design/designing-side-quests-study-these-7-games-and-some-chris-avellone-pointers-)
- [Rampant Games (Jay Barnson)](http://rampantgames.com/blog/?p=4028)
- [Silverarm Press](https://silverarmpress.com/better-side-quests/)
- [Tribality](https://www.tribality.com/2021/09/07/what-makes-a-good-side-quest/)
- [TTRPG Games](https://www.ttrpg-games.com/blog/side-quest-design-tips)

### NQ-5. Make choices consequential, not false

Each option should carry a real trade-off (something gained and something lost) with no
single dominant or obviously-correct answer, outcomes should visibly diverge or be
acknowledged later, and "false choices" that converge to the same result should be
avoided, because players quickly detect and disengage from them.

Sources:
- [Game Developer (Sid Meier, interesting decisions)](https://www.gamedeveloper.com/design/gdc-2012-sid-meier-on-how-to-see-games-as-sets-of-interesting-decisions)
- [Game Developer: Meaning and choice](https://www.gamedeveloper.com/design/meaning-and-choice-or-how-to-design-decisions-that-feel-intimately-difficult)
- [Emily Short (Choice Poetics)](https://emshort.blog/2019/04/09/choice-poetics-peter-mawhorter/)
- [Game Informer](https://gameinformer.com/b/features/archive/2015/02/03/why-your-choices-dont-matter-in-telltale-games.aspx)
- [PC Gamer](https://www.pcgamer.com/im-over-the-fact-that-choices-dont-really-matter-in-telltale-games/)
- [Extra Credits](https://www.youtube.com/watch?v=lg8fVtKyYxY)

### NQ-6. Build NPCs from a clear internal core

Design characters and NPCs from a clear internal core (goals/agenda, wants vs needs,
fears, flaws) and let their dialogue, decisions, and behavior flow from it. Even minor
NPCs benefit from one or two specific, memorable traits or an agenda so their
interactions feel distinct, though minor NPCs need only light specificity.

Sources:
- [Game Developer: Compelling video game characters](https://www.gamedeveloper.com/design/key-ingredients-for-compelling-video-game-characters)
- [The Alexandrian](https://thealexandrian.net/wordpress/43539/roleplaying-games/random-gm-tip-memorable-npcs)
- [Juego Studio](https://www.juegostudio.com/blog/key-principles-character-design-video-games)
- [Dice Monkey](https://www.dicemonkey.net/2024/07/01/crafting-memorable-npcs-a-guide-to-bringing-your-rpg-to-life/)
- [TTRPG-Games (NPC motivations)](https://www.ttrpg-games.com/blog/ultimate-guide-to-npc-motivations/)
- [Roll for Fantasy](https://rollforfantasy.com/guides/character-goals-motivations.php)

### NQ-7. Treat foreshadowing as a two-way contract

Every prominent element you deliberately call attention to (a Chekhov's gun) must
eventually pay off, and every major payoff must be planted earlier. Cut introduced
elements that never resolve, and avoid reveals with no setup, so climaxes feel earned
rather than arbitrary. In interactive contexts, a planted element may be an option
rather than a guaranteed firing.

Sources:
- [StudioBinder](https://www.studiobinder.com/blog/chekhovs-gun/)
- [Wikipedia: Chekhov's gun](https://en.wikipedia.org/wiki/Chekhov's_gun)
- [Script Magazine](https://scriptmag.com/features/column-d-setup-and-payoff-writing-foreshadowing-script)
- [Scribophile](https://www.scribophile.com/academy/what-is-chekhovs-gun)
- [Game Developer: Foreshadowing in games](https://www.gamedeveloper.com/design/7-great-examples-of-foreshadowing-in-games-that-devs-should-study)
- [Helping Writers Become Authors](https://www.helpingwritersbecomeauthors.com/setup-and-payoff-the-two-equally-important-halves-of-story-foreshadowing/)
- [Encyclopaedia Britannica](https://www.britannica.com/topic/Chekhovs-gun)

### NQ-8. Shape pacing as an intensity curve

Deliberately alternate high-intensity peaks with quieter rest and reflective valleys so
players are neither numbed nor bored, use a midpoint shift that raises stakes and turns
the protagonist from reactive to proactive, and escalate toward a climax. The climactic
encounter need not be the single hardest beat; emotional intensity and a brief falling
action also matter.

Sources:
- [Game Developer: Harnessed pacing intensity](https://www.gamedeveloper.com/design/gameplay-fundamentals-revisited-harnessed-pacing-intensity)
- [The Level Design Book](https://book.leveldesignbook.com/process/preproduction/pacing)
- [World of Level Design](https://www.worldofleveldesign.com/categories/wold-members-tutorials/peteellis/level-design-pacing-gameplay-beats-part2.php)
- [USC Scalar](https://scalar.usc.edu/works/interactive-storytelling-narrative-techniques-and-methods-in-video-games/pacing)
- [Helping Writers Become Authors (midpoint)](https://www.helpingwritersbecomeauthors.com/story-structure-midpoint/)
- [The Welsh Piper](https://welshpiper.com/three-act-adventures/)

### NQ-9. Align mechanics with theme (ludonarrative harmony)

Align mechanics with the narrative theme so player actions reinforce what the story
asserts; mechanics that embody the game's values deepen immersion, while mismatch (the
classic "selfless hero" whose mechanics reward slaughter) creates dissonance that pulls
players out of the fiction. This is a strong default, not an absolute: dissonance can be
deployed intentionally as a rhetorical device.

Sources:
- [Wikipedia: Ludonarrative dissonance](https://en.wikipedia.org/wiki/Ludonarrative_dissonance)
- [Game Developer: Meaning through mechanics](https://www.gamedeveloper.com/design/conveying-meaningful-messages-through-mechanics)
- [Michael Ghelfi Studios](https://www.michaelghelfistudios.com/ludonarrative-harmony-tabletop-games/)
- [Blood Moon Interactive](https://www.bloodmooninteractive.com/articles/ludonarrative-dissonance-and-harmony.html)
- [The Strong National Museum of Play (Brenda Romero)](https://www.museumofplay.org/blog/brenda-romero-the-mechanic-is-the-message/)
- [A Game Design Vocabulary (Anthropy and Clark)](https://www.befreed.ai/book/a-game-design-vocabulary-by-anna-anthropy)

---

# Text-world and MUD craft

### MUD-1. Make NPCs react in context

Attach trigger-driven behavior to NPCs so they react in context: greeting players who
enter, responding to speech and emotes, varying behavior by time of day, and reacting
to player actions. Reactive NPCs turn a zone of silent, motionless mobs (which reads as
scenery) into an inhabited, responsive world.

Sources:
- [Writing Games (mobprogs)](https://writing-games.org/text-game-terms/mobprog-definition-mprog-examples/)
- [Mimic Gaming](https://www.mimicgaming.com/post/how-npcs-in-video-games-make-worlds-feel-real)
- [Muds Wiki (Mobprogs)](https://muds.fandom.com/wiki/Mobprogs)
- [Evennia](https://www.evennia.com/docs/0.x/Evennia-Introduction.html)
- [Discworld MUD](http://discworld.starturtle.net/lpc/playing/documentation.c?path=%2Fnewbie%2Fnpc_interaction)

### MUD-2. Design for all four Bartle types and tune their ratios

Design for achievers, explorers, socializers, and killers, and actively tune their
ratios, because the types form a feedback system: too many killers drives off
socializers and achievers, achievers attract socializers, and explorers are the only
lever that lowers killers without bleeding other groups. Over-serving or starving any
one type pushes the population away from equilibrium.

Sources:
- [Richard Bartle (mud.co.uk)](https://mud.co.uk/richard/hcds.htm)
- [Envato Tuts+](https://code.tutsplus.com/bartles-taxonomy-of-player-types-and-why-it-doesnt-apply-to-everything--gamedev-4173a)
- [Andrew Fischer Games](https://andrewfischergames.com/blog/bartles-taxonomy)
- [CJ Leo Game Design Blog](https://cjleo.com/blog/beyond-bartles-taxonomy-discover-your-games-player-types/)
- [aeStranger](https://aestranger.com/personality-types-part-3-socialiser/)

### MUD-3. Engineer emergent social play through interdependence

Make players genuinely need one another (specialized crafting, player-driven economies,
trade, weak-tie reliance) and give them persistent places to gather. Worlds built on
mutual dependence and sociability generate their own stories, foster community, retain
players, and even reduce griefing, turning a solo content treadmill into a
self-sustaining society.

Sources:
- [Raph Koster (Designing a living society in SWG)](https://www.raphkoster.com/2015/04/21/designing-a-living-society-in-swg-part-one/)
- [Massively Overpowered](https://massivelyop.com/2021/04/10/playable-worlds-raph-koster-shares-the-secret-of-good-social-design-in-mmos/)
- [Game Developer (CCP on EVE)](https://www.gamedeveloper.com/business/interview-evolution-and-risk-ccp-on-the-freedoms-of-eve-online)
- [Oxford Academic (JCMC)](https://academic.oup.com/jcmc/article/11/4/885/4617703)
- [MMORPG.com](https://www.mmorpg.com/editorials/beyond-quests-and-raids-player-driven-mmorpgs-when-players-become-world-architects-2000134552)
- [SUPERJUMP Magazine](https://www.superjumpmagazine.com/the-rise-of-digital-third-spaces/)

### MUD-4. Keep room descriptions short and scannable

Keep room and scene descriptions short and scannable (a few sentences, on the order of
about 50 to 80 words or fewer) and front-load strong, evocative verbs and tightly
chosen adjectives instead of long literary paragraphs, because players skim and re-read
rooms at speed and lose navigational cues when prose runs long.

Sources:
- [Roleplaying Tips](https://www.roleplayingtips.com/running-games/description-sorcery-from-a-wordsmithing-warlock/)
- [Discworld MUD (writer's block)](https://discworld.starturtle.net/lpc/about/articles/writers_block.html)
- [Game Developer: The ancient art of the MUD](https://www.gamedeveloper.com/design/the-ancient-art-of-the-mud-a-writer-s-perspective-of-the-crafting-of-a-text-based-game-)
- [Writing Games (room length)](https://writing-games.org/how-long-should-room-descriptions-be-in-a-mud/)
- [D&D Beyond (boxed text)](https://www.dndbeyond.com/posts/625-lets-design-an-adventure-boxed-text)
- [sub-Q Magazine](https://sub-q.com/room-descriptions-place-and-interiority/)

### MUD-5. Render mood through the non-visual senses; do not narrate emotion

Do not state the player's emotion or force a reaction ("You feel terrified"). Instead,
render the environment through deliberate non-visual senses (sound, smell, temperature,
texture) so each location is inferred as a distinct, recallable mood. In text the named
senses are the only graphics you have.

Sources:
- [Game Developer: The ancient art of the MUD](https://www.gamedeveloper.com/design/the-ancient-art-of-the-mud-a-writer-s-perspective-of-the-crafting-of-a-text-based-game-)
- [Writing Games (room descriptions)](https://writing-games.org/writing-room-descriptions-tips-and-examples/)
- [Emily Short (the prose medium and IF)](https://emshort.blog/how-to-play/writing-if/my-articles/the-prose-medium-and-if/)
- [Writing Crucible](https://writingcrucible.com/journal/weaving-worlds-with-words-sensory-details-and-atmospheric-descriptions-in-fantasy)
- [Hopper's Writing Nook](https://www.hopperswritingnook.com/post/unlocking-immersion-using-sensory-details-to-bring-your-writing-to-life)

### MUD-6. Keep maps reciprocal and legible

Make movement reciprocal and geometrically consistent (going one direction and back
returns you where you started), keep newbie and starting zones free of disorienting
mazes and inescapable rooms, and surface exits through directional cues in the room's
prose rather than relying solely on a mechanical exits line. This keeps the world
legible and reinforces the player's mental map.

Sources:
- [Raph Koster (a spatial representation)](https://www.raphkoster.com/games/insubstantial-pageants/a-spatial-representation/)
- [CircleMUD Builder's Manual](https://www.circlemud.org/cdp/building/building-2.html)
- [Advent of the Mists (room guidelines)](https://adventmud.org/builders/building-getting-started/building-rooms/room-guidelines/)
- [Emily Short (geography)](https://emshort.blog/how-to-play/writing-if/my-articles/geography/)
- [Interactive Fiction Forum](https://intfiction.org/t/describing-room-directions/9245)
- [Wikibooks: Inform 7 guide](https://en.wikibooks.org/wiki/Beginner's_Guide_to_Interactive_Fiction_with_Inform_7/Getting_Started_with_Inform_7)

### MUD-7. Implement every object you name

Any noun a player can reasonably try to examine should return real, specific text
rather than a generic refusal, and meaningful player actions should produce a visible,
consistent change in world state. Mentioning a thing creates an implicit promise of
interactivity; unfulfilled promises and stock refusals break immersion and train
players to stop exploring.

Sources:
- [Entropic Thoughts](https://entropicthoughts.com/lessons-from-creating-first-text-adventure)
- [Chris Ainsley (text adventure design)](https://medium.com/@model_train/text-adventure-game-design-in-2020-608528ac8bda)
- [The Inform 7 Handbook](https://inform-7-handbook.readthedocs.io/en/latest/chapter_2_rooms_&_scenery/scenery/)
- [Advent of the Mists](https://adventmud.org/builders/building-getting-started/building-rooms/room-guidelines/)
- [GameDesignSkills](https://gamedesignskills.com/game-design/text-based/)
- [Interactive Fiction Forum](https://intfiction.org/t/object-descriptions-more-of-a-best-practices-question/53335)

---

# Combat and progression math

MudProto tunes these through `configuration/attributes/` (combat severity, classes,
experience, level scaling) and the combat modules under `core_logic/`.

### CM-1. Keep working numbers small and legible

Default to small, legible HP and damage values (roughly single to triple digits) so
players can build an accurate mental model and track combat math in their heads. Treat
large numbers as spectacle, not a balance default, and if progression forces scale to
inflate, add a reset/prestige or stat-squish valve plus number formatting to pull
values back into a readable range.

Sources:
- [Game Developer: The math of idle games III](https://www.gamedeveloper.com/design/the-math-of-idle-games-part-iii)
- [InformIT / Pearson (Game Systems Design)](https://www.informit.com/articles/article.aspx?p=3128856&seqNum=2)
- [Alexander King (good numbers)](https://www.literallyaking.com/blog/good-numbers-part1)
- [Blizzard Watch (Diablo damage numbers)](https://blizzardwatch.com/2016/01/25/diablo-damage-numbers-changed/)
- [The Nameless Quality](https://namelessquality.com/tech-design-high-vs-low-granularity/)
- [EN World (bounded accuracy)](https://www.enworld.org/threads/explain-bounded-accuracy-to-me-as-if-i-was-five.703031/)

### CM-2. Keep the core attribute set small and legible

Keep the core attribute set small and meaningful (about 3 to 6 primary attributes that
drive derived combat stats), make how those stats convert into outcomes legible to
players, and tune so secondary stats and alternative builds stay viable rather than
collapsing to a single dominant strategy.

Sources:
- [Game Developer: Design 101, Balancing Games](https://www.gamedeveloper.com/design/design-101-balancing-games)
- [Sirlin.net](https://www.sirlin.net/articles/balancing-multiplayer-games-part-1-definitions)
- [Wikipedia: Attribute (role-playing games)](https://en.wikipedia.org/wiki/Attribute_(role-playing_games))
- [Choice of Games (7 rules for stats)](https://www.choiceofgames.com/2011/07/7-rules-for-designing-great-stats/)
- [Choice of Games stat design (Diablo IV tooltips, Blizzard forums)](https://us.forums.blizzard.com/en/d4/t/heres-how-to-improve-damage-transparency-via-contextualized-tooltips/247765)
- [TV Tropes: Three Stat System](https://tvtropes.org/pmwiki/pmwiki.php/Main/ThreeStatSystem)

### CM-3. Tune around time-to-kill and integer breakpoints

Balance combat against time-to-kill and integer damage breakpoints (the number of hits
a kill actually takes), not continuous DPS. Because outcomes resolve in whole hits, a
small stat change that crosses a breakpoint (turning a 5-hit kill into a 4-hit kill)
discontinuously flips fights, so tune and reason about the breakpoint a change lands on,
not just its average effect.

Sources:
- [Game Developer: How balance affects difficulty](https://www.gamedeveloper.com/design/how-balance-can-affect-difficulty)
- [EA / Respawn (Apex Designer's Notes)](https://www.ea.com/en/games/apex-legends/apex-legends/news/27-1-designers-notes)
- [GDC Vault (Titanfall)](https://gdcvault.com/play/1024056/Solving-Titan-Sized-Problems-Evolving)
- [GameDesignSkills](https://gamedesignskills.com/game-design/battle-royale/)
- [PC Gamer (Destiny 2 TTK)](https://www.pcgamer.com/destiny-2-ramps-up-pvp-weapon-damage-for-quicker-time-to-kill/)
- [Dot Esports (MW3 TTK)](https://dotesports.com/call-of-duty/news/what-is-modern-warfare-3s-ttk)

### CM-4. Treat percentage armor's diminishing returns as a feature

For percentage/rating-based armor, the apparent diminishing returns are an artifact of
expressing mitigation as a percentage. Each point of armor reduces a smaller slice of
raw damage but adds a roughly constant amount of effective HP, so effective health
scales linearly and the stat never stops being worth buying. Do not "fix" the
percentage curve as if it were broken.

Sources:
- [League of Legends Wiki](https://wiki.leagueoflegends.com/en-us/Armor)
- [Liquipedia (Dota 2 Armor)](https://liquipedia.net/dota2/Armor)
- [Warcraft Wiki](https://warcraft.wiki.gg/wiki/Armor)
- [Dotabuff](https://www.dotabuff.com/blog/2018-11-30-understanding-720-armor-changes)
- [MOBAFire](https://www.mobafire.com/profile/darkpercy-22031/blog/lol-maths-clarifying-some-misconceptions-answer-to-darkpercy)

### CM-5. Prefer divisive mitigation over flat subtraction

Prefer divisive (percentage) damage mitigation of the form
`damage_taken = damage * K/(K + defense)` over flat subtractive defense, because the
divisive form gives smooth diminishing returns, never fully negates a hit, and scales
gracefully across power levels. Anchor the constant K to a fixed global value or to the
attacker's level, never to the defender's own stat.

Sources:
- [Warcraft Wiki](https://warcraft.wiki.gg/wiki/Armor)
- [League of Legends Wiki](https://wiki.leagueoflegends.com/en-us/Armor)
- [Liquipedia (Dota 2 Armor)](https://liquipedia.net/dota2/Armor)
- [Guild Wars 2 Wiki](https://wiki.guildwars2.com/wiki/Damage)
- [Warframe Wiki](https://wiki.warframe.com/w/Armor)
- [Guild Wars Wiki](https://wiki.guildwars.com/wiki/Armor_rating)

---

# Difficulty, balance, and tuning

### DT-1. Counter runaway feedback loops with balancing loops

Positive (reinforcing) feedback loops let an early lead compound into a near-certain
runaway winner; counter them with negative (balancing) loops or catch-up mechanics to
keep outcomes contested. Tune them carefully and keep comebacks earned, since overt or
overpowered catch-up nullifies player agency and makes early skill feel meaningless.

Sources:
- [Wikipedia: Game balance](https://en.wikipedia.org/wiki/Game_balance)
- [Machinations.io](https://machinations.io/articles/game-systems-feedback-loops-and-how-they-help-craft-player-experiences)
- [Chemeketa Community College (CIS125G)](https://computerscience.chemeketa.edu/cis125greader/MechanicsDynamics/FeedbackLoops.html)
- [Amsterdam University of Applied Sciences](https://tkdev.dss.cloud/gamedesign/toolkit/feedback-loops/)
- [daniel.games (catch-up mechanics)](https://daniel.games/catch-up-mechanics/)
- [Riot Games (comeback mechanics)](https://www.leagueoflegends.com/en-us/news/dev/quick-gameplay-thoughts-2-25-comeback-mechanics/)

### DT-2. Hunt dominant strategies; give every strong option a counter

A competitive game is balanced when many options stay viable in expert play. Actively
hunt for dominant or degenerate strategies (any tactic that reliably wins with no
effective counter), because a single uncounterable option collapses the strategy space.
Ensure every strong option has a counter, ideally an intransitive
rock-paper-scissors web, so no one tactic crowds out the rest.

Sources:
- [Sirlin.net](https://www.sirlin.net/articles/balancing-multiplayer-games-part-1-definitions)
- [Wikipedia: Game balance](https://en.wikipedia.org/wiki/Game_balance)
- [Game Developer: What is degenerate](https://www.gamedeveloper.com/design/what-is-quot-degenerate-quot-)
- [Game Balance Concepts (Ian Schreiber)](https://gamebalanceconcepts.wordpress.com/2010/09/01/level-9-intransitive-mechanics/)
- [Ludism.org](https://www.ludism.org/gamedesign/RockPaperScissors)
- [80 Level](https://80.lv/articles/how-strategy-games-apply-the-rock-paper-scissors-mechanic)
- [tis.so (Salen and Zimmerman, Rules of Play)](https://tis.so/degenerate-play)

### DT-3. Build play from interesting decisions with real trade-offs

Present several viable options, none strictly dominant, make each trade a genuine
benefit against a genuine cost (often a safe small payoff versus a risky large one,
"triangularity"), and give the player enough information to weigh the choice. When one
option is always best, the decision becomes meaningless.

Sources:
- [Wikipedia: Game balance](https://en.wikipedia.org/wiki/Game_balance)
- [Sirlin.net](https://www.sirlin.net/articles/balancing-multiplayer-games-part-1-definitions)
- [Game Design Concepts (Ian Schreiber)](https://gamedesignconcepts.wordpress.com/2009/08/20/level-16-game-balance/)
- [Lost Garden (Daniel Cook, value chains)](https://lostgarden.com/2021/12/12/value-chains/)
- [Game Wisdom (risk/reward)](https://game-wisdom.com/general/risk-reward-player-agency-video-games-casino-games-get-right-wrong)

### DT-4. Design for perceived fairness, not just correct math

Players systematically misread true randomness (streaks read as "rigged"), so make the
relationship between stats and outcomes legible and, where it matters, smooth the
variance (pseudo-random distribution, bad-luck protection, and on lower difficulties a
slight tilt toward the player) so that what feels fair lines up with the underlying math.

Sources:
- [Liquipedia (Pseudo Random Distribution)](https://liquipedia.net/dota2/Pseudo_Random_Distribution)
- [Game Developer: Perceptions of randomness](https://www.gamedeveloper.com/design/perceptions-of-randomness-social-games-and-game-design)
- [GamesBeat (Sid Meier)](https://gamesbeat.com/game-guru-sid-meier-explains-decades-of-second-guessing-egomaniacal-gamers/)
- [Old School RuneScape Wiki (bad luck mitigation)](https://oldschool.runescape.wiki/w/Bad_luck_mitigation)
- [Wikipedia: Gambler's fallacy](https://en.wikipedia.org/wiki/Gambler%27s_fallacy)
- [GDC Vault: The Psychology of Game Design](https://www.gdcvault.com/play/1012186/The-Psychology-of-Game-Design)

### DT-5. Keep difficulty in the flow channel

Tune the difficulty of successive zones as a gradually rising curve that keeps challenge
roughly matched to the player's growing skill, the flow channel between boredom
(challenge below skill) and anxiety (challenge above skill), and break up sustained
high-intensity stretches with calmer sections so pacing rises and falls.

Sources:
- [Wikipedia: Game balance](https://en.wikipedia.org/wiki/Game_balance)
- [Game Developer: The chemistry of game design](https://www.gamedeveloper.com/design/the-chemistry-of-game-design)
- [Jenova Chen (Flow in Games)](https://www.jenovachen.com/flowingames/introduction.htm)
- [PositivePsychology.com (flow)](https://positivepsychology.com/what-is-flow/)
- [Level Design Book (pacing)](https://book.leveldesignbook.com/process/preproduction/pacing)

### DT-6. Pace and layer rewards; keep grind optional

Offer several parallel advancement streams (XP, unlocks, crafting, reputation), vary the
activities that earn them to prevent monotony and burnout, and keep heavy grinding
optional rather than gating meaningful progress behind disproportionate time for
marginal gains.

Sources:
- [Wikipedia: Grinding (video games)](https://en.wikipedia.org/wiki/Grinding_(video_games))
- [Wikipedia: Overjustification effect](https://en.wikipedia.org/wiki/Overjustification_effect)
- [Game Developer: The chemistry of game design](https://www.gamedeveloper.com/design/the-chemistry-of-game-design)
- [Game Developer: Exploitationware (Ian Bogost)](https://www.gamedeveloper.com/design/persuasive-games-exploitationware)
- [Raph Koster (Laws of Online World Design)](https://www.raphkoster.com/games/laws-of-online-world-design/the-laws-of-online-world-design/)
- [Richard Bartle (mud.co.uk)](https://mud.co.uk/richard/hcds.htm)

### DT-7. Prefer input randomness over output randomness

Favor input randomness, revealed before the player commits so they can plan around it,
over output randomness, which strikes after the decision and can negate good play; and
bound overall variance so skill rather than luck is the dominant determinant of
outcomes.

Sources:
- [Game Developer: Randomness and game design](https://www.gamedeveloper.com/design/randomness-and-game-design)
- [Skeleton Code Machine](https://www.skeletoncodemachine.com/p/input-output-randomness-part-1)
- [The Board Game Design Course](https://boardgamedesigncourse.com/the-2-types-of-randomness/)
- [Level 99 Games](https://www.level99store.com/blogs/guidelines/3-5-1-3-5-2-input-output-randomness)
- [daniel.games (randomness)](https://daniel.games/randomness/)
- [Entro Games](https://entrogames.substack.com/p/019-input-vs-output-randomness-a-couple-of-words-out-of-order-and-more)

### DT-8. Tune against telemetry and playtests, not intuition

Instrument the game with telemetry and run structured playtests, then quantify how
options actually perform (win/pick/usage and success rates) and re-tune the statistical
outliers (options used or winning far more or less than expected) instead of relying on
designer intuition alone.

Sources:
- [Wikipedia: Game balance](https://en.wikipedia.org/wiki/Game_balance)
- [Springer (Game Analytics, Drachen et al.)](https://cmps-people.ok.ubc.ca/bowenhui/game/readings/ch2-game-metrics.pdf)
- [GDC Vault (online game optimization)](https://www.gdcvault.com/play/1015462/Optimization-of-Online-Games-through)
- [Riot Games (champion balance framework)](https://www.leagueoflegends.com/en-us/news/dev/dev-champion-balance-framework/)
- [AAAI AIIDE](https://ojs.aaai.org/index.php/AIIDE/article/view/12513)
- [arXiv (Zook, Fruchter, Riedl)](https://arxiv.org/abs/1908.01417)

### DT-9. Use dynamic difficulty adjustment subtly when a fixed curve cannot fit

When a single fixed curve cannot fit every player, continuously read performance
signals (deaths, completion time, accuracy, resource state) and smoothly modulate
pacing, spawn intensity, and resource availability to keep each player in the flow
channel. Make adjustments gradual and largely imperceptible, since players who notice
the system can feel cheated or game it.

Sources:
- [Wikipedia: Dynamic game difficulty balancing](https://en.wikipedia.org/wiki/Dynamic_game_difficulty_balancing)
- [Northwestern University (Robin Hunicke)](https://users.cs.northwestern.edu/~hunicke/thesis.html)
- [Springer (Multimedia Tools and Applications)](https://link.springer.com/article/10.1007/s11042-024-18768-x)
- [IntechOpen](https://www.intechopen.com/chapters/1228576)
- [StraySpark Studio](https://www.strayspark.studio/blog/difficulty-systems-players-enjoy)
- [Design The Game](https://www.designthegame.com/learning/tutorial/mastering-dynamic-difficulty-adjustments-dda-player-engagement)

---

# Economy and rewards

MudProto already has coins, merchants (`commerce.py`), and loot; tune these as a system.

### EC-1. Anchor item value in scarcity and bind the most prestigious rewards

Item value rests on real scarcity plus utility: if supply is uncontrolled, botting and
mass-farming flood the market and collapse worth. Anchor value by limiting sources and
adding sinks, and bind the most prestigious rewards (bind-on-pickup / soulbound) so they
cannot be farmed for resale and devalued.

Sources:
- [Wikipedia: Virtual economy](https://en.wikipedia.org/wiki/Virtual_economy)
- [Wikipedia: Gold farming](https://en.wikipedia.org/wiki/Gold_farming)
- [Raph Koster (economy)](https://www.raphkoster.com/gaming/economy.shtml)
- [Yu-kai Chou (sinks before sources)](https://yukaichou.com/gamification-analysis/economy-design-sources-sinks-confidence/)
- [Mises Institute (A Virtual Weimar)](https://mises.org/mises-daily/virtual-weimar-hyperinflation-video-game-world)
- [Fandom (Diablo Wiki: Soulbound)](https://diablo-archive.fandom.com/wiki/Soulbound)

### EC-2. Model loot as explicit weighted drop tables

Model loot as explicit weighted drop tables in which every outcome (including a
deliberate no-drop entry) has a numeric weight, and gate rarer entries behind harder,
more-gated content so the randomness produces earned anticipation instead of meaningless
noise.

Sources:
- [Game Developer / Lost Garden (Daniel Cook)](https://www.gamedeveloper.com/design/loot-drop-best-practices)
- [Old School RuneScape Wiki (drop table)](https://oldschool.runescape.wiki/w/Drop_table)
- [Minecraft Wiki (loot table)](https://minecraft.wiki/w/Loot_table)
- [Wikipedia: Loot (video games)](https://en.wikipedia.org/wiki/Loot_(video_games))
- [Blizzard (Diablo II Resurrected forums)](https://us.forums.blizzard.com/en/d2r/t/what-player-count-in-game-actually-does-to-drops/106237)

### EC-3. Model currency as an explicit faucet and sink flow

Instrument how much each faucet mints and each sink removes, deliberately size recurring
sinks so net removal roughly matches or exceeds minting to hold prices stable, and
re-audit and re-tune both sides whenever new content shifts the balance.

Sources:
- [Wikipedia: Virtual economy](https://en.wikipedia.org/wiki/Virtual_economy)
- [Yu-kai Chou (Octalysis)](https://yukaichou.com/gamification-analysis/economy-design-sources-sinks-confidence/)
- [CCP Games (EVE patch notes)](https://www.eveonline.com/news/view/patch-notes-version-22-02)
- [arXiv (Hogan-Hennessy et al.)](https://arxiv.org/abs/2210.07970)
- [Outer Directive (how MMO economies work)](https://www.outerdirective.com/blog/how-mmo-economies-work)

### EC-4. Assume gold-farming and RMT; design defensively

Assume gold-farming, botting, and real-money trading are persistent rather than
eliminable. Raise the per-account cost of mass account creation and automation, inject
unpredictable gameplay and human-verification checks that bots cannot cheaply automate,
and ensure any sanctioned marketplace never lets players bypass the core kill-loot
reward loop that drives engagement.

Sources:
- [Engadget (gold trading exposed)](https://www.engadget.com/2009-03-24-gold-trading-exposed-a-look-at-multi-billion-dollar-grey-marke.html)
- [Verisoul (bot prevention)](https://www.verisoul.ai/articles/the-silent-war-advanced-bot-prevention-strategies-in-modern-gaming)
- [Old School RuneScape Wiki (random events)](https://oldschool.runescape.wiki/w/Random_events)
- [ScreenRant (Diablo Immortal auction house)](https://screenrant.com/diablo-immortal-director-auction-house-3-myth-debunk/)
- [Wikipedia: Gold farming](https://en.wikipedia.org/wiki/Gold_farming)
- [University of Cambridge (bot army index)](https://www.cam.ac.uk/stories/price-bot-army-global-index)

### EC-5. Cap random drop streaks with bad-luck protection

Layer bad-luck protection over random drop systems: ramp the odds with each miss (soft
pity / pseudo-random distribution) and/or guarantee a payout after a fixed number of
failed attempts (hard pity). This caps the worst-case dry streak, bounding frustration
while preserving the variance and excitement of randomized rewards.

Sources:
- [Wikipedia: Loot box](https://en.wikipedia.org/wiki/Loot_box)
- [Liquipedia (Pseudo Random Distribution)](https://liquipedia.net/dota2/Pseudo_Random_Distribution)
- [Old School RuneScape Wiki (pity rate)](https://oldschool.runescape.wiki/w/Pity_rate)
- [Riot Games](https://www.leagueoflegends.com/en-us/news/game-updates/dev-exalted-skins-the-mythic-shop-and-nexus-finishers/)
- [Hearthstone Wiki (pity timer)](https://hearthstone.wiki.gg/wiki/Card_pack)
- [Game Anatomy](https://gameanatomy.blog/2025/05/03/pity-timers-in-games-explained/)

### EC-6. Use variable-ratio rewards ethically

Variable-ratio (intermittent) random-reward schedules produce the most persistent
engagement of any reinforcement schedule, but they are structurally the same mechanism
as slot-machine gambling and are linked to compulsive spending and harm (especially in
minors). Apply them ethically: cap their intensity, disclose the odds, and never charge
real money for the random pull.

Sources:
- [Wikipedia: Compulsion loop](https://en.wikipedia.org/wiki/Compulsion_loop)
- [Yu-kai Chou (operant conditioning)](https://yukaichou.com/gamification-study/gamification-and-operant-conditioning/)
- [UBC Centre for Brain Health](https://www.centreforbrainhealth.ca/news/when-gaming-leads-to-gambling-the-risks-of-loot-boxes/)
- [Nature Human Behaviour](https://www.nature.com/articles/s41562-018-0360-1)
- [Royal Society Open Science](https://pmc.ncbi.nlm.nih.gov/articles/PMC9382208/)
- [Journal of Gambling Issues](https://cdspress.ca/wp-content/uploads/2022/05/JGI-Jul-21-POL-022.R2-FINAL-Clean.pdf)

---

# Not yet gated (candidates below the five-source bar)

These ideas are widely held and likely correct, but did not reach five independent
sources in this pass (the web-search backend was degraded during verification). Treat
them as candidates, apply judgment, and re-verify before adopting as hard heuristics.

- **XP curve pacing.** Prefer an XP curve whose between-level increases grow gently (a
  polynomial or linear-increment curve, not raw exponential) and tune it against time
  (hours per level), front-loading fast early levels because slow early progression
  loses players. (Reached 4 independent sources.)
- **Additive within a category, multiplicative sparingly.** Keep most modifiers additive
  within a category and reserve multiplicative bonuses for a few deliberate slots,
  because independent multiplicative sources compound into runaway damage. (Widely held;
  not independently re-confirmed to five sources this pass.)
- **Smooth, monotonic stat-to-effect mappings.** Avoid hidden breakpoints where a stat
  suddenly changes effectiveness, so improving a character always intuitively helps.
- **Meaningful upgrades change how an item plays,** not just its numbers, paced so each
  tier unlocks the next challenge. (Reached 4 independent sources.)
- **Readable feedback as the core reward.** Give clear, immediate, proportionate
  cause-and-effect responses and introduce mechanics one at a time.
- **Cross-check reward-to-difficulty across every zone** so no area is absurdly
  rewarding or punishing relative to the rest.

---

# MudProto application checklist

Use when authoring content or tuning systems in this repo.

- World content (rooms, zones, NPCs, items) is internally consistent with established
  lore and the magic/affect model (WB-1, WB-2, MG-1).
- Geography, cultures, names, and history are causally grounded, not arbitrary
  (WB-3, WB-5, WB-6, WB-7).
- Room descriptions are short, sensory, and legible, with reciprocal exits and named
  objects that respond (MUD-4, MUD-5, MUD-6, MUD-7).
- Quests carry context, stakes, and a twist; choices have real trade-offs; lore is
  drip-fed (NQ-1, NQ-4, NQ-5).
- New spells/skills define limits and costs before power, ration through vigor/mana and
  cooldowns, and reuse the shared affect model (MG-2, MG-3, MG-6, MG-5).
- Combat changes are reasoned at small, legible numbers and at time-to-kill breakpoints,
  with divisive mitigation and viable build diversity (CM-1, CM-2, CM-3, CM-5, DT-2).
- Difficulty rises along a flow curve; no dominant strategy; randomness favors planning
  and bounds streaks (DT-5, DT-2, DT-7, EC-5).
- Economy changes keep faucets and sinks balanced, anchor item value in scarcity, and do
  not introduce gambling-style monetized randomness (EC-1, EC-3, EC-6).

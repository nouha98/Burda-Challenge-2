RECIPE DATASET — TECHNICAL README

1. FILES AND XML STRUCTURE

The archive contains 5,000 recipe XML files:
- rezepte_export/: one original, unchanged XML file per recipe.
- auswahl_manifest.json: recipe index, file paths, classification metadata and checksums.
- README.txt: this document.

The recipes and source field names retain their original language.

Format: XML 1.0, UTF-8.
Root element: document, with attributes id, dcx-version="6.3.1" and version="1.0".
Default namespace: http://www.digicol.com/xmlns/dcx

Recipe fields are located under head. Other elements, such as created, modified,
pool_id and files, contain administrative metadata. body uses an XHTML namespace;
read the structured recipe content from head.

XML queries must account for the default namespace. In the table below, d is a
query prefix bound to http://www.digicol.com/xmlns/dcx. Paths are relative to
document; attributes and child elements marked "within" refer to the stated group.

| Information | XML path / attributes |
| --- | --- |
| Recipe ID | @id on document |
| Title | d:head/d:Headline; fallback: d:head/d:Title |
| Subtitle | d:head/d:SubHeadline (optional) |
| Ingredient group | d:head/d:CustomRecipeIngredients; @taggroup_id |
| Ingredient group heading | Within ingredient group: d:CustomRecipeIngredientsHeader (optional) |
| Ingredient | Within ingredient group: d:CustomRecipeIngredient |
| Ingredient name / ID | On ingredient: @plural / @topic; the name may be missing |
| Quantity | On ingredient: @amount; preserve the original value |
| Upper quantity bound | On ingredient: @amount_max or @max_amount; both spellings occur |
| Unit | On ingredient: @unit; @unit_topic is an internal unit reference |
| Ingredient modifiers | On ingredient: @prefix and @suffix |
| Ingredient order | On ingredient: @position within its group, where available |
| Preparation step group | d:head/d:CustomRecipePreparationSteps; @taggroup_id |
| Preparation text | Within step group: d:CustomRecipePreparationsStepsContent |
| Step label | Within step group: d:CustomRecipePreparationStepsLabel |
| Step heading | Within step group: d:CustomRecipePreparationsStepsHeader (optional) |
| Tips | d:head/d:CustomRecipeTipps/d:CustomRecipeTippsContent |
| Yield / servings | d:head/d:CustomRecipeServing; @amount, @plural, @topic |
| Preparation times | d:head/d:CustomRecipePreparation; @minutes, @topic, optionally @name |
| Difficulty | d:head/d:CustomRecipeDifficulty; @topic |
| Nutrition | Element text in d:head/d:CustomRecipeNutritionalValueCalories, CustomRecipeNutritionalValueKilojoule, CustomRecipeNutritionalValueCarbs, CustomRecipeNutritionalValueProtein and CustomRecipeNutritionalValueFat |
| Category references | d:head/d:CustomRecipeThesaurs and d:head/d:Keywords; @topic |
| Image reference | d:head/d:Image/d:DocumentRef; @doc_id, @file_variant |
| Additional recipe JSON | d:head/d:CustomStructuredRecipeJson (optional) |

CustomRecipePreparationsStepsContent and CustomRecipeThesaurs are the actual field
names, including their unusual spelling.

Preserve group order. Within each ingredient group, sort by position when all
positions are numeric; otherwise retain XML order. Keep quantities and units as
raw values until normalized. Missing values are not zero. Preserve any
amount_error, amount_max_error and ingredient_error attributes as quality flags.
Do not automatically sum different preparation time types into a total duration.

2. DATA AVAILABILITY AND LIMITATIONS

| Availability in this archive | Number of recipes |
| --- | ---: |
| Title, structured ingredients and preparation text | 5,000 |
| Names present for every XML ingredient | 4,697 |
| At least one XML ingredient name missing | 303 |
| Additional recipe JSON present and successfully parsed | 2,014 |
| No additional recipe JSON | 2,986 |
| Yield / serving amount present | 4,986 |
| At least one preparation time present | 4,863 |
| At least one of the five nutrition fields listed above present | 3,565 |
| Non-empty tip text | 1,729 |

- Internal IDs are references, not readable ingredient names or category labels.
  A lookup source is required to resolve them; no separate lookup definitions
  are included. Do not invent missing labels.
- Missing ingredient names prevent reliable confirmation of strict ingredient
  exclusions. Treat unresolved conditions as unknown or requiring review.
- Additional JSON is optional. Parse the XML first, then parse the element text
  as JSON; XML entities are already decoded by the XML parser. Flag conflicts
  between XML fields and JSON instead of silently replacing values.
- Optional fields may be absent or empty. Preserve unknown values and omit
  unavailable display fields. Do not assume nutrition values are per serving
  unless their reference quantity is explicitly established.
- Image references do not include image files. No recipe image assets are
  supplied in the archive.
- Classification labels are not verified dietary claims. A vegetable-related
  category, for example, does not establish that a recipe is vegetarian.
- Ingredient groups and text lengths vary; any output layout must handle
  variable content. The data has not undergone a complete culinary review.

3. USING THE MANIFEST

auswahl_manifest.json contains one entry per recipe in the rezepte array.
Use it to locate XML files and retain a stable link to each source recipe.
Field names and stored values are unchanged; the table explains them in English.

| Manifest field | Meaning |
| --- | --- |
| id | Recipe ID; matches document/@id in the XML |
| datei | XML file path relative to the archive root |
| titel | Recipe title |
| hauptkategorie | One assigned primary category |
| weihnachtsrezept | Existing Christmas classification flag |
| zuordnungsbeleg_im_titel, weihnachtsbezug | Recorded classification evidence and rationale |
| sha256 | SHA-256 checksum of the original XML bytes |
| zutaten_anzahl | Number of structured ingredients |
| zutaten_mit_klarnamen | Number of ingredients with readable names |
| zubereitungsschritte_anzahl | Number of non-empty preparation text entries |

Classification metadata is a starting point, not an exhaustive description of
recipe suitability. Consult the XML content for more detailed criteria. Verify
file integrity against sha256 using the original file bytes, before modifying
or reserializing the XML.

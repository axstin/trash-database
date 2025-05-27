# parse and import data from TRaSH Guides

import os
import json
import re
import yaml
import copy

def hash_dict(value):
    return hash(json.dumps(value, sort_keys=True))

def sanitize_file_name(name):
    return "".join(c for c in name if c.isalpha() or c.isdigit() or c in " _-+.").rstrip()

def load_json(path):
    result = {}
    for file_name in sorted(os.listdir(path), reverse=True):
        file_path = os.path.join(path, file_name)
        if file_name.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as file:
                contents = json.load(file)
            
            contents["_path"] = file_path
            contents["_id"] = file_name[:-5]
            result[contents["_id"]] = contents
        elif os.path.isdir(file_path):
            result[file_name] = load_json(file_path)
    return result

class CustomFormat:
    def __init__(self, data, origin):
        self.data = data
        self.hash = hash_dict(data["specifications"])
        self.origin = origin
        self.id = data["_id"]
        self.path = data["_path"]
        self.description = None

        # load description
        for name in (f"{self.id}-{origin}.md", f"{self.id}.md"):
            try:
                with open("wiki/includes/cf-descriptions/%s" % name, "r", encoding="utf-8") as file:
                    contents = file.read()
                    m = re.search(r"<br>\n+([\s\S]+?)(?=<!|$)", contents)
                    assert m is not None, "failed to parse %s" % name
                    self.description = "\n\n" + m.group(1).strip()
            except OSError as e:
                pass

        if self.description is None:
            print("warning: failed to find description for %s" % self.path)
            self.description = ""

        self.description = "**Imported from %s**" % repr(self) + self.description

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        return self.data["specifications"] == other.data["specifications"]

    def __getitem__(self, index):
        return self.data[index]

    def __str__(self):
        #return "%s [%s]" % (self.data["_path"], self.data["name"])
        return self.data["name"]

    def __repr__(self):
        return "%s/%s" % (self.origin, self.id)

class ProfilarrCustomFormat:
    def __init__(self, data, source: CustomFormat=None, source_id=None):
        self.data = data
        self.hash = hash_dict(data["conditions"])
        self.source = source

        if source_id is not None:
            self.id = source_id
        else:
            assert source is not None
            self.id = source.id

    def __hash__(self):
        return self.hash

    def __eq__(self, other):
        return self.data["conditions"] == other.data["conditions"]

    def __getitem__(self, index):
        return self.data[index]

    def __setitem__(self, index, value):
        self.data[index] = value

    def __str__(self):
        return self.data["name"]

    def __repr__(self):
        return self.id

def find_or_create_pattern(patterns, name, value, source):
    pattern = next((x for x in patterns if x["pattern"] == value), None)
    name = name.removeprefix("Not ").strip()
    if pattern is not None:
        if not pattern["name"].lower().startswith(name.lower()):
           print("notice: found pattern with matching values but different names (import name: %s, existing name: %s)" % (name, pattern["name"]))
        return pattern["name"]
    else:
        # use dictionarry's regexes over trash's
        # this is fine as long as both are trying to do the same thing...
        # darry_pattern = next((x for x in patterns if x["name"].lower() == name.lower() and "TRaSH" not in x["tags"]), None)
        # if darry_pattern is not None:
        #     print("WARNING: preferring Dictionarry regex over TRaSH for '%s'" % name)
        #     print(" - Dictionarry: %s" % darry_pattern["pattern"])
        #     print(" - TRaSH: %s" % value)
        #     return darry_pattern

        # lol
        original_name = name
        change_count = 0
        while next((x for x in patterns if x["name"].lower() == name.lower()), None) is not None:
            change_count += 1
            name = "%s-%u" % (original_name, change_count + 1)

        if change_count > 0:
            print("notice: found duplicate name '%s' while creating pattern, using '%s'" % (original_name, name))

        pattern = {
            "name": name,
            "pattern": value,
            "description": "TRaSH pattern imported from %s" % source,
            "tags": [ "TRaSH" ],
            "tests": None
        }

        patterns.append(pattern)

        return name


def convert_condition(spec, cf: CustomFormat, patterns):
    # https://github.com/Dictionarry-Hub/profilarr/blob/main/backend/app/compile/format_compiler.py
    # https://github.com/Dictionarry-Hub/profilarr/blob/main/backend/app/compile/mappings.py

    cond = {}
    cond["name"] = spec["name"]
    cond["negate"] = spec["negate"]
    cond["required"] = spec["required"]

    spec_type = spec["implementation"]
    spec_value = spec["fields"].get("value")

    if spec_type == "ReleaseTitleSpecification":
        cond["type"] = "release_title"
        cond["pattern"] = find_or_create_pattern(patterns, spec["name"], spec_value, repr(cf))
    elif spec_type == "ReleaseGroupSpecification":
        cond["type"] = "release_group"
        cond["pattern"] = find_or_create_pattern(patterns, spec["name"], spec_value, repr(cf))
    elif spec_type == "EditionSpecification":
        cond["type"] = "edition"
        cond["pattern"] = find_or_create_pattern(patterns, spec["name"], spec_value, repr(cf))
    elif spec_type == "SourceSpecification":
        cond["type"] = "source"
        
        mapping = {
            "radarr": {
                '1': 'cam',
                '2': 'telesync',
                '3': 'telecine',
                '4': 'workprint',
                '5': 'dvd',
                '6': 'tv',
                '7': 'web_dl',
                '8': 'webrip',
                '9': 'bluray'
            },

            "sonarr": {
                '1': 'television',
                '2': 'televisionraw',
                '3': 'web_dl',
                '4': 'webrip',
                '5': 'dvd',
                '6': 'bluray',
                '7': 'blurayraw'
            }
        }

        cond["source"] = mapping[cf.origin][str(spec_value)]
    elif spec_type == "ResolutionSpecification":
        cond["type"] = "resolution"
        assert spec_value in (360, 480, 540, 576, 720, 1080, 2160)
        cond["resolution"] = "%up" % spec_value 
    elif spec_type == "IndexerFlagSpecification":
        cond["type"] = "indexer_flag"
        
        mapping = {
            "radarr": {
                '1': 'freeleech',
                '2': 'halfleech',
                '4': 'double_upload',
                '32': 'internal',
                '128': 'scene',
                '256': 'freeleech_75',
                '512': 'freeleech_25',
                '2048': 'nuked',
                '8': 'ptp_golden',
                '16': 'ptp_approved'
            },

            "sonarr": {
                '1': 'freeleech',
                '2': 'halfleech',
                '4': 'double_upload',
                '8': 'internal',
                '16': 'scene',
                '32': 'freeleech_75',
                '64': 'freeleech_25',
                '128': 'nuked'
            }
        }

        cond["flag"] = mapping[cf.origin][str(spec_value)]
    elif spec_type == "QualityModifierSpecification":
        cond["type"] = "quality_modifier"
        
        assert cf.origin == "radarr"

        mapping = {
            '0': 'none',
            '1': 'regional',
            '2': 'screener',
            '3': 'rawhd',
            '4': 'brdisk',
            '5': 'remux',
        }

        cond["qualityModifier"] = mapping[str(spec_value)]
    elif spec_type == "SizeSpecification":
        cond["type"] = "size"
        # no use of SizeSpecification in TRaSH docs
        assert False, "not implemented"
    elif spec_type == "YearSpecification":
        cond["type"] = "year"
        # no use of YearSpecification in TRaSH docs
        assert False, "not implemented"
    elif spec_type == "ReleaseTypeSpecification":
        cond["type"] = "release_type"

        assert cf.origin == "sonarr"

        mapping = {
            '0': 'none',
            '1': 'single_episode',
            '2': 'multi_episode',
            '3': 'season_pack'
        }

        cond["releaseType"] = mapping[str(spec_value)]
    elif spec_type == "LanguageSpecification":
        cond["type"] = "language"
        
        mapping = {
            "radarr": {
                '-1': 'any',
                '-2': 'original',
                '0': 'unknown',
                '1': 'english',
                '2': 'french',
                '3': 'spanish',
                '4': 'german',
                '5': 'italian',
                '6': 'danish',
                '7': 'dutch',
                '8': 'japanese',
                '9': 'icelandic',
                '10': 'chinese',
                '11': 'russian',
                '12': 'polish',
                '13': 'vietnamese',
                '14': 'swedish',
                '15': 'norwegian',
                '16': 'finnish',
                '17': 'turkish',
                '18': 'portuguese',
                '19': 'flemish',
                '20': 'greek',
                '21': 'korean',
                '22': 'hungarian',
                '23': 'hebrew',
                '24': 'lithuanian',
                '25': 'czech',
                '26': 'hindi',
                '27': 'romanian',
                '28': 'thai',
                '29': 'bulgarian',
                '30': 'portuguese_br',
                '31': 'arabic',
                '32': 'ukrainian',
                '33': 'persian',
                '34': 'bengali',
                '35': 'slovak',
                '36': 'latvian',
                '37': 'spanish_latino',
                '38': 'catalan',
                '39': 'croatian',
                '40': 'serbian',
                '41': 'bosnian',
                '42': 'estonian',
                '43': 'tamil',
                '44': 'indonesian',
                '45': 'telugu',
                '46': 'macedonian',
                '47': 'slovenian',
                '48': 'malayalam',
                '49': 'kannada',
                '50': 'albanian',
                '51': 'afrikaans',
            },
            "sonarr": {
                '0': 'unknown',
                '1': 'english',
                '2': 'french',
                '3': 'spanish',
                '4': 'german',
                '5': 'italian',
                '6': 'danish',
                '7': 'dutch',
                '8': 'japanese',
                '9': 'icelandic',
                '10': 'chinese',
                '11': 'russian',
                '12': 'polish',
                '13': 'vietnamese',
                '14': 'swedish',
                '15': 'norwegian',
                '16': 'finnish',
                '17': 'turkish',
                '18': 'portuguese',
                '19': 'flemish',
                '20': 'greek',
                '21': 'korean',
                '22': 'hungarian',
                '23': 'hebrew',
                '24': 'lithuanian',
                '25': 'czech',
                '26': 'arabic',
                '27': 'hindi',
                '28': 'bulgarian',
                '29': 'malayalam',
                '30': 'ukrainian',
                '31': 'slovak',
                '32': 'thai',
                '33': 'portuguese_br',
                '34': 'spanish_latino',
                '35': 'romanian',
                '36': 'latvian',
                '37': 'persian',
                '38': 'catalan',
                '39': 'croatian',
                '40': 'serbian',
                '41': 'bosnian',
                '42': 'estonian',
                '43': 'tamil',
                '44': 'indonesian',
                '45': 'macedonian',
                '46': 'slovenian',
                '-2': 'original',
            }
        }

        cond["language"] = mapping[cf.origin][str(spec_value)]
        assert "exceptLanguage" not in spec["fields"]
    else:
        assert False, "unknown implementation %s" % spec_type

    return cond

def convert_format(cf: CustomFormat, patterns):
    result = {}
    result["name"] = cf["name"]
    result["description"] = cf.description
    result["tags"] = [ "TRaSH", cf["name"] ]

    conditions = []
    for spec in cf["specifications"]:
        conditions.append(convert_condition(spec, cf, patterns))

    result["conditions"] = conditions

    return ProfilarrCustomFormat(result, cf)   

def collect_formats(root, arr):
    result = set()
    for name, data in root[arr]["cf"].items():
        cf = CustomFormat(data, arr)
        if cf in result:
            print("notice: found duplicate custom format '%s' in %s (existing: %s), ignoring" % (cf, arr, next(x for x in result if x == cf)))
        else:
            result.add(cf)
    return result

def convert_formats(root, arr, existing_formats, patterns):
    result = set()
    for name, data in root[arr]["cf"].items():
        cf = convert_format(CustomFormat(data, arr), patterns)
        if cf in result:
            print("notice: found duplicate custom format '%s' in %s (existing: %s), ignoring" % (cf, arr, next(x for x in result if x == cf)))
        elif cf in existing_formats:
            print("notice: found duplicate custom format '%s' in Dictionarry (existing: %s), ignoring" % (cf, next(x for x in existing_formats if x == cf)))
        else:
            result.add(cf)
    return result

def load_yaml(path):
    result = []
    for file_name in os.listdir(path):
        if file_name.endswith(".yml"):
            with open(os.path.join(path, file_name), "r", encoding="utf-8") as file:
                result.append(yaml.safe_load(file))
    return result

def load_formats(path):
    result = set()
    for file_name in os.listdir(path):
        if file_name.endswith(".yml"):
            with open(os.path.join(path, file_name), "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                pcf = ProfilarrCustomFormat(data, source_id=file_name)
                if pcf in result:
                    print("notice: found duplicate custom format '%s' in custom_formats (existing: %s), ignoring" % (pcf, next(x for x in result if x == pcf)))
                else:
                    result.add(pcf)
    return result

print("Removing trash-*.yml format files...")
for name in os.listdir("../custom_formats"):
    if name.startswith("trash-"):
        os.remove("../custom_formats/%s" % name)

print("Removing trash-*.yml regex files...")
for name in os.listdir("../regex_patterns"):
    if name.startswith("trash-"):
        os.remove("../regex_patterns/%s" % name)

darry_cfs = load_formats("../custom_formats")
patterns = load_yaml("../regex_patterns")
root = load_json("wiki/docs/json/")

radarr_cfs = convert_formats(root, "radarr", darry_cfs, patterns)
sonarr_cfs = convert_formats(root, "sonarr", darry_cfs, patterns)

shared_cfs = sorted(list(radarr_cfs & sonarr_cfs), key=lambda x: x["name"])
radarr_only_cfs = sorted(list(radarr_cfs - sonarr_cfs), key=lambda x: x["name"])
sonarr_only_cfs = sorted(list(sonarr_cfs - radarr_cfs), key=lambda x: x["name"])

print("Shared CFs (size=%u):" % len(shared_cfs))
#print(shared_cfs)

print("Radarr CFs (size=%u):" % len(radarr_only_cfs))
#print(radarr_only_cfs)

print("Sonarr CFs (size=%u):" % len(sonarr_only_cfs))
#print(sonarr_only_cfs)

for cf in shared_cfs:
    cf["name"] = "[TRaSH] %s" % cf["name"]

for cf in radarr_only_cfs:
    cf["name"] = "[TRaSH] [Radarr] %s" % cf["name"]
    cf["tags"].append("TRaSH Radarr")
    cf.id = "radarr-%s" % cf.id

for cf in sonarr_only_cfs:
    cf["name"] = "[TRaSH] [Sonarr] %s" % cf["name"]
    cf["tags"].append("TRaSH Sonarr")
    cf.id = "sonarr-%s" % cf.id

# format files
print("Writing TRaSH custom formats...")
for cfs in [ shared_cfs, radarr_only_cfs, sonarr_only_cfs ]:
    for cf in cfs:
        with open("../custom_formats/trash-%s.yml" % cf.id, "w", encoding="utf-8") as file:
            yaml.dump(cf.data, file, sort_keys=False)

# regex files
print("Writing TRaSH regex files...")
seen = set()
for pattern in patterns:
    if "TRaSH" in pattern["tags"]:
        file_name = sanitize_file_name(pattern["name"])
        assert file_name not in seen, "duplicate file %s (from %s)" % (file_name, pattern["name"])
        seen.add(file_name)
        with open("../regex_patterns/trash-%s.yml" % file_name, "w", encoding="utf-8") as file:
            yaml.dump(pattern, file, sort_keys=False)

print("Done")












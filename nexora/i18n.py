"""Extensible message catalog. User-authored content is never machine translated."""
import json
import re
from pathlib import Path

_catalog = None

PREFIXES = {
    'Your Telegram user ID: ': 'നിങ്ങളുടെ Telegram അംഗ ID: ',
    'Private dashboard link (expires in one hour):': 'സ്വകാര്യ ഡാഷ്ബോർഡ് ലിങ്ക് (ഒരു മണിക്കൂറിൽ കാലാവധി കഴിയും):',
    'Give Nexora the Telegram permission: ': 'Nexoraക്ക് ഈ Telegram അനുമതി നൽകുക: ',
    'Report recorded: ': 'റിപ്പോർട്ട് രേഖപ്പെടുത്തി: ', 'Federation ID: ': 'ഫെഡറേഷൻ ID: ',
    'Selected destination: ': 'തിരഞ്ഞെടുത്ത ലക്ഷ്യസ്ഥാനം: ', 'Draft saved: ': 'ഡ്രാഫ്റ്റ് സേവ് ചെയ്തു: ',
    'Type: ': 'ടൈപ്പ് ചെയ്യുക: ', 'Capabilities: ': 'അനുമതികൾ: ',
    'Unresolved support ticket: ': 'പരിഹരിക്കാത്ത സപ്പോർട്ട് ടിക്കറ്റ്: ',
    'Name similarity needs administrator review: member ': 'പേര് സാമ്യം അഡ്മിൻ പരിശോധിക്കണം; അംഗം ',
    'Raid protection active: bot-enforced lockdown for non-admin messages. ': 'കൂട്ട ആക്രമണ സംരക്ഷണം സജീവം: അഡ്മിൻ അല്ലാത്തവരുടെ സന്ദേശങ്ങൾക്ക് ബോട്ട് നിയന്ത്രണം. ',
    'AI draft — check accuracy.': 'AI കരട് — കൃത്യത പരിശോധിക്കുക.',
    'Approved sources: ': 'അംഗീകരിച്ച സ്രോതസ്സുകൾ: ',
    'Nexora — groups, publishing and support in one bot.': 'Nexora — ഗ്രൂപ്പ്, പ്രസിദ്ധീകരണം, സപ്പോർട്ട് ഒരിടത്ത്.',
    'Group: ': 'ഗ്രൂപ്പ്: ', 'Moderation: ': 'മോഡറേഷൻ: ', 'Config: ': 'ക്രമീകരണം: ',
    'Content: ': 'ഉള്ളടക്കം: ', 'Tools: ': 'ഉപകരണങ്ങൾ: ', 'Federations: ': 'ഫെഡറേഷനുകൾ: ',
    'Private: ': 'സ്വകാര്യമായി: ', 'Group administrators: ': 'ഗ്രൂപ്പ് അഡ്മിനുകൾ: ',
    'Support: ': 'സപ്പോർട്ട്: ', 'Publishing: ': 'പ്രസിദ്ധീകരണം: ', 'Publishing (private): ': 'പ്രസിദ്ധീകരണം (സ്വകാര്യമായി): ',
    'Support admins: ': 'സപ്പോർട്ട് അഡ്മിനുകൾ: ', 'Super admins (private): ': 'സൂപ്പർ അഡ്മിനുകൾ (സ്വകാര്യമായി): ',
    'Private identity: ': 'സ്വകാര്യ തിരിച്ചറിയൽ: ',
}
PATTERNS = [
    (r'Warning recorded \((\d+)\)\.', r'മുന്നറിയിപ്പ് രേഖപ്പെടുത്തി (\1).'),
    (r'Queued for (\d+) opted-in users\.', r'സമ്മതം നൽകിയ \1 അംഗങ്ങൾക്ക് ക്യൂവിൽ ചേർത്തു.'),
    (r'Queued job (\d+)\. Scheduled content is a snapshot; /reschedule refreshes it\.', r'ജോലി \1 ക്യൂവിൽ ചേർത്തു. ഉള്ളടക്കം ഒരു പകർപ്പാണ്; /reschedule പുതുക്കും.'),
    (r'Ticket (\w+) \| user (\d+)\nReply to this header or the copied message\.', r'ടിക്കറ്റ് \1 | അംഗം \2\nഈ തലക്കെട്ടിനോ പകർത്തിയ സന്ദേശത്തിനോ മറുപടി നൽകുക.'),
    (r'Appeal (approved|rejected): (.*)', r'അപ്പീൽ തീരുമാനം (\1): \2'),
    (r'Messages: (\d+) \| Active users: (\d+)\nObserved members: (\d+)\nPrivate /dashboard (-?\d+) for charts \(admins\)\.', r'സന്ദേശങ്ങൾ: \1 | സജീവ അംഗങ്ങൾ: \2\nകണ്ട അംഗങ്ങൾ: \3\nചാർട്ടുകൾക്ക് സ്വകാര്യമായി /dashboard \4 (അഡ്മിനുകൾ).'),
    (r'Campaign (\w+) queued\. /announce_status (\w+)', r'ക്യാമ്പെയ്ൻ \1 ക്യൂവിൽ ചേർത്തു. /announce_status \2'),
    (r'Preview (\w+): (\d+) eligible destinations; (\d+) could not be checked\.\nTo send within 15 minutes: /announce_send (\w+) CONFIRM\nRecipients and permissions are checked again at delivery\. Nothing has been queued yet\.', r'പ്രിവ്യൂ \1: \2 യോഗ്യമായ ലക്ഷ്യസ്ഥാനങ്ങൾ; \3 പരിശോധിക്കാനായില്ല.\n15 മിനിറ്റിനുള്ളിൽ അയക്കാൻ: /announce_send \4 CONFIRM\nഅയക്കുമ്പോൾ അനുമതികൾ വീണ്ടും പരിശോധിക്കും. ഇതുവരെ ക്യൂവിൽ ചേർത്തിട്ടില്ല.'),
]


def catalog():
    global _catalog
    if _catalog is None:
        path = Path(__file__).with_name('locales.json')
        _catalog = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return _catalog


def translate(text, language='en'):
    if language == 'en':
        # Legacy bilingual responses remain accepted while explicit catalogs take precedence.
        return catalog().get(text, {}).get('en', text)
    exact = catalog().get(text, {}).get(language)
    if exact:
        return exact
    if language != 'ml':
        return text
    for pattern,replacement in PATTERNS:
        if re.fullmatch(pattern,text,flags=re.S):
            return re.sub(pattern,replacement,text,flags=re.S)
    lines=[]
    for line in text.split('\n'):
        translated=catalog().get(line,{}).get(language)
        if translated is None:
            translated=line
            for prefix,value in PREFIXES.items():
                if line.startswith(prefix):
                    translated=value+line[len(prefix):]
                    break
        lines.append(translated)
    return '\n'.join(lines)

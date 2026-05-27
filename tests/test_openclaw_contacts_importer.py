from openclaw_contacts_importer import decode_contact_text, import_contacts_csv, import_contacts_vcf, normalize_phone
from openclaw_targets_manager import OpenClawTargetsManager


def test_normalize_phone_variants():
    assert normalize_phone("34611111111") == "+34611111111"
    assert normalize_phone("722-129-717") == "+34722129717"
    assert normalize_phone("(+34) 722 129 717") == "+34722129717"


def test_import_contacts_csv_creates_targets(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    csv_data = b'name,phone,aliases,relationship,favorite\nLaura,+34722129717,"mi novia,novia,Laura",novia,true\n'

    summary = import_contacts_csv(csv_data, manager)
    target = manager.find_best_match("whatsapp", "mi novia")

    assert summary["success"] is True
    assert summary["created"] == 1
    assert target["canonical_target"] == "+34722129717"
    assert target["favorite"] is True
    assert target["source"] == "contacts_import"


def test_import_contacts_csv_normalizes_and_skips_missing_phone(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    csv_data = "name,phone\nMamá,34611111111\nSinTelefono,\nConGuiones,722-129-717\n".encode("utf-8")

    summary = import_contacts_csv(csv_data, manager)

    assert summary["created"] == 2
    assert summary["skipped"] == 1
    assert manager.find_best_match("whatsapp", "Mamá")["canonical_target"] == "+34611111111"
    assert manager.find_best_match("whatsapp", "ConGuiones")["canonical_target"] == "+34722129717"


def test_import_contacts_csv_avoids_duplicates(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    csv_data = b"name,phone\nLaura,+34722129717\nLaura Dos,+34722129717\n"

    summary = import_contacts_csv(csv_data, manager)

    assert summary["created"] == 1
    assert summary["updated"] == 1
    assert len(manager.list_targets()) == 1


def test_import_contacts_vcf_basic(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    vcf = b"BEGIN:VCARD\nVERSION:3.0\nFN:Laura\nTEL;TYPE=CELL:722 129 717\nEND:VCARD\n"

    summary = import_contacts_vcf(vcf, manager)

    assert summary["created"] == 1
    assert manager.find_best_match("whatsapp", "Laura")["canonical_target"] == "+34722129717"


def test_import_contacts_vcf_decodes_quoted_printable_names_and_emoji(tmp_path):
    manager = OpenClawTargetsManager(tmp_path / "targets.json")
    vcf = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=4D=69=20=4E=69=C3=B1=61=61=61=E2=9D=A4\n"
        "TEL;TYPE=CELL:+34722129717\n"
        "END:VCARD\n"
    ).encode("utf-8")

    summary = import_contacts_vcf(vcf, manager)
    target = manager.find_by_canonical_target("whatsapp", "+34722129717")

    assert summary["created"] == 1
    assert target["display_name"] == "Mi Niñaaa❤"
    assert decode_contact_text("=41=6E=64=72=C3=A9=73") == "Andrés"

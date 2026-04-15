import os
import shutil
from pathlib import Path

source_dir = Path(r"C:\Users\EL PUTO MACABRO\Desktop\Habilidades Antigravity")
dest_dir = Path(r"C:\Users\EL PUTO MACABRO\Desktop\motor-tributario-conect\.agents\skills")

print(f"Importando habilidades de {source_dir} para {dest_dir}...\n")

if not dest_dir.exists():
    dest_dir.mkdir(parents=True, exist_ok=True)

count = 0
for file_path in source_dir.glob("*.md"):
    # Ignora arquivos de documentação padrão que não são skills
    if file_path.name.upper() in ["README.md", "CLAUDE.md"]:
        continue
    
    skill_name = file_path.stem
    skill_folder = dest_dir / skill_name
    skill_folder.mkdir(exist_ok=True)
    
    dest_file = skill_folder / "SKILL.md"
    shutil.copy2(file_path, dest_file)
    print(f"✅ [{skill_name}] -> {dest_file.relative_to(dest_dir.parent.parent)}")
    count += 1

print(f"\n🏁 Concluído! {count} habilidades estruturadas no formato '[nome-da-skill]/SKILL.md'.")

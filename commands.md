
# Restaurar la ultima version de GITHUB
git fetch origin; git reset --hard origin/main; git clean -fd

# Correr pruebas unitarias
python -m unittest tests/test_cryptobot.py

# Actualizar el repositorio
git init
git add .
git commit -m "Your message"
git remote add origin https://github.com/orlandobatistac/cryptobot.git
git push -u origin main

# Ver que se va a subir a git
git config --global alias.check 'status --ignored'
git check


# ✅ Flujo seguro para commits en tu proyecto (Git)

Este archivo resume los pasos que debes seguir para trabajar con Git sin subir archivos ignorados como `debug.log`, `data/`, `__pycache__/`, etc.

---

## 1. 🔄 Verifica el estado del proyecto

git status

- Muestra archivos modificados, nuevos, eliminados o ignorados.
- Úsalo siempre antes de hacer `git add`.

---

## 2. ➕ Agrega los cambios válidos

git add .

- Agrega todos los archivos nuevos y modificados **excepto** los que están en `.gitignore`.
- Si accidentalmente agregaste algo que debería estar ignorado, elimínalo con:

git rm --cached ruta/del/archivo

---

## 3. 💬 Crea el commit

git commit -m "Descripción breve del cambio"

Ejemplos:

git commit -m "Fix bug in EMA crossover logic"  
git commit -m "Add new backtest config"

---

## 4. 🚀 Sube tus cambios al repositorio remoto

git push

---

## 🧼 ¿Qué hacer si `.gitignore` no está funcionando?

1. Asegúrate de tener las reglas correctas en `.gitignore`:

debug.log  
__pycache__/  
data/  
results/

2. Elimina todo del índice (sin borrar del disco):

git rm -r --cached .

3. Vuelve a agregar solo lo válido:

git add .  
git commit -m "Clean tracked files that should be ignored"  
git push

---

## 🧠 Trucos útiles

| Comando                    | Qué hace                                                    |
|---------------------------|--------------------------------------------------------------|
| git status                | Ver qué está listo, ignorado o no trackeado                  |
| git add .                 | Agrega todos los cambios válidos                             |
| git rm --cached archivo   | Elimina del control de Git, pero no del disco                |
| git commit -m "mensaje"   | Crea el commit                                               |
| git push                  | Sube al repo remoto                                          |


# 1. Crear una nueva rama sin historial
git checkout --orphan latest-commit

# 2. Agregar todos los archivos y crear un nuevo commit
git add .
git commit -m "Reset history and keep latest version"

# 3. Eliminar la rama main anterior
git branch -D main

# 4. Renombrar la nueva rama a main
git branch -m main

# 5. Agregar el remoto si no está configurado
git remote add origin https://github.com/USUARIO/REPO.git

# 6. Hacer push forzado al nuevo historial
git push -f origin main

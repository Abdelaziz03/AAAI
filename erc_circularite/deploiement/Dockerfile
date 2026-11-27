# Image du dossier, sans données : elles arrivent par des volumes au lancement.
#   docker build -f deploiement/Dockerfile -t erc-circularite .        (depuis le dossier erc_circularite)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /opt/erc_circularite
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Un compte sans privilège : le dossier n'a besoin d'écrire que dans ses propres sous-dossiers.
RUN useradd --create-home --uid 10001 erc \
 && mkdir -p artefacts parametres cortex demo \
 && chown -R erc:erc /opt/erc_circularite
USER erc
ENTRYPOINT ["python", "-m"]
CMD ["erc.agent"]

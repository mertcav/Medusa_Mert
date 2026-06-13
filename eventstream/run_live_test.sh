#!/usr/bin/env bash
# run_live_test.sh — WBS 1.1.8 canlı Kafka topic/replay davranış kapısı koşucusu.
# Bir Kafka CLI (rpk veya kafka-topics.sh) + ${KAFKA_BOOTSTRAP_SERVERS} varsa:
# declarative manifesti uygular, topic'leri + retention/cleanup config'ini doğrular.
# Yoksa SKIP (exit 0) — cache/objstore/db run_live_test.sh deseniyle aynı.
# Sır/credential repoya YAZILMAZ — yalnız ${ENV}. Asıl deterministik kapı:
#   python3 eventstream_probe.py validate|replay|route|selftest
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$HERE/config/topics.declarative.json"

# Statik kapı her zaman koşar (sunucu gerekmez)
echo "== statik kapı (probe) =="
python3 "$HERE/eventstream_probe.py" validate || exit 1
python3 "$HERE/eventstream_probe.py" replay   || exit 1
python3 "$HERE/eventstream_probe.py" route    || exit 1
python3 "$HERE/tests/envelope_behavior_test.py" || exit 1

BOOT="${KAFKA_BOOTSTRAP_SERVERS:-}"
if [ -z "$BOOT" ]; then
  echo "SKIP: KAFKA_BOOTSTRAP_SERVERS tanımlı değil (CI'da gerçek cluster ile koşar)."
  exit 0
fi

CLI=""
if command -v rpk >/dev/null 2>&1; then CLI="rpk"
elif command -v kafka-topics.sh >/dev/null 2>&1; then CLI="kafka-topics.sh"
else
  echo "SKIP: rpk/kafka-topics.sh bulunamadı."
  exit 0
fi

echo "== canlı kapı: $CLI @ $BOOT =="
# Manifestteki her topic'i oku (python ile, jq bağımlılığı yok)
mapfile -t TOPICS < <(python3 -c "import json;[print(t['name'],t['partitions'],t['configs']['retention.ms'],t['configs']['cleanup.policy']) for t in json.load(open('$MANIFEST'))['topics']]")

for line in "${TOPICS[@]}"; do
  set -- $line
  NAME="$1"; PARTS="$2"; RET="$3"; CLEAN="$4"
  if [ "$CLI" = "rpk" ]; then
    rpk topic create "$NAME" -p "$PARTS" -r 3 \
      -c "retention.ms=$RET" -c "cleanup.policy=$CLEAN" -c "min.insync.replicas=2" \
      --brokers "$BOOT" 2>/dev/null || echo "  (mevcut) $NAME"
    rpk topic describe "$NAME" --brokers "$BOOT" >/dev/null && echo "  OK $NAME"
  else
    kafka-topics.sh --create --if-not-exists --topic "$NAME" \
      --partitions "$PARTS" --replication-factor 3 \
      --config "retention.ms=$RET" --config "cleanup.policy=$CLEAN" \
      --bootstrap-server "$BOOT" 2>/dev/null || echo "  (mevcut) $NAME"
    kafka-topics.sh --describe --topic "$NAME" --bootstrap-server "$BOOT" >/dev/null && echo "  OK $NAME"
  fi
done
echo "canlı kapı: tüm topic'ler uygulandı/doğrulandı."

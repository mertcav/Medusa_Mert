#!/bin/bash
# orchestrator.sh — login'li (abonelik) Claude Code ile docs/todo_list.md görevlerini
# TASK BAZLI işler: yalnızca İLK açık görevi ([ ]) Claude'a verir, sonucu işaretler ve DURUR.
# (Bir sonraki görev için scripti yeniden çalıştır.)
set -u

unset ANTHROPIC_API_KEY            # abonelik (OAuth) kullansın, API key DEĞİL

# --- Yapılandırma (env ile override edilebilir) ---
TODO="${TODO:-docs/todo_list.md}"      # işlenecek görev dosyası
AUTO_GIT="${AUTO_GIT:-1}"             # 1 ise tamamlanan görev sonrası commit dener
AUTO_PUSH="${AUTO_PUSH:-1}"           # 1 ise her commit sonrası GitHub'a push eder
GIT_BRANCH="${GIT_BRANCH:-chanteur-docs}"  # push edilecek dal (main DEĞİL: remote'ta başka proje var)
# NOT: Kimlik doğrulama git credential store'dan gelir (~/.git-credentials).
#      Token bu script'e YAZILMAZ; repoya commit edilmez.

mkdir -p docs reports

if [ ! -f "$TODO" ]; then
  echo "HATA: $TODO yok. Önce TODO dosyasını yerleştir."; exit 1
fi
if ! command -v claude >/dev/null 2>&1; then
  echo "HATA: 'claude' CLI bulunamadı (Claude Code kurulu mu, login mi?)."; exit 1
fi

# git opsiyonel: repo değilse commit adımını sessizce atla
git_enabled=0
if [ "$AUTO_GIT" = "1" ] && command -v git >/dev/null 2>&1 \
   && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_enabled=1
fi

# İlk açık görevin satır numarası ( - [ ] ... ; backtick'li lejant satırını atlar)
lineno=$(grep -n -m1 -E '^[[:space:]]*-[[:space:]]*\[[[:space:]]\][[:space:]]+[^`]' "$TODO" | cut -d: -f1)
if [ -z "$lineno" ]; then
  echo ">> Tüm görevler tamamlandı (açık [ ] görev kalmadı)."; exit 0
fi

# Görev metnini çıkar ( "- [ ] " önekini ve markdown bold yıldızlarını temizle )
task=$(sed -n "${lineno}p" "$TODO" \
       | sed -E 's/^[[:space:]]*-[[:space:]]*\[[[:space:]]\][[:space:]]*//' \
       | sed -E 's/\*\*//g')
echo "=== Görev (satır $lineno): $task ==="

safe=$(echo "$task" | tr -c '[:alnum:]' '_' | cut -c1-50)
logfile="reports/$(date +%s)_${safe}.log"

claude -p "Sadece şu TEK görevi yap: $task
CLAUDE.md'deki akışı ve $TODO'daki talimatları izle: analiz, plan, geliştir, test, bugfix.
Kaynak gereksinimler için docs/BRD.md ve docs/SAD.md esastır; FR-ID şemasını ve doküman stilini bozma.
Çalışmanı reports/ altına markdown rapor olarak da yaz.
Görev başarıyla bitince çıktının EN SON satırına yalnızca: DONE
Devam edemiyorsan EN SON satıra yalnızca: BLOCKED (nedenini bir üst satırda açıkla)." \
    --permission-mode acceptEdits \
    --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
    --output-format text \
    < /dev/null | tee "$logfile"

if grep -qE '^[[:space:]]*BLOCKED[[:space:]]*$' "$logfile"; then
  echo "!!! BLOCKED: '$task' — duruyorum. Log: $logfile"
  sed -i "${lineno}s/\[ \]/[!]/" "$TODO"
  echo ">> Bitti (BLOCKED). Durum: $TODO"; exit 2
elif grep -qE '^[[:space:]]*DONE[[:space:]]*$' "$logfile"; then
  sed -i "${lineno}s/\[ \]/[x]/" "$TODO"
  if [ "$git_enabled" = "1" ]; then
    git add -A && git commit -m "feat: $task" >/dev/null 2>&1 || true
    if [ "$AUTO_PUSH" = "1" ]; then
      git push origin "$GIT_BRANCH" >/dev/null 2>&1 \
        && echo "    (push: origin/$GIT_BRANCH OK)" \
        || echo "    (UYARI: git push başarısız — log/ağ/kimlik kontrol et)"
    fi
  fi
  echo "=== Tamamlandı ve işaretlendi: $task ==="
  echo ">> Bitti (1 görev tamamlandı). Durum: $TODO"; exit 0
else
  echo "??? Net sonuç yok (DONE/BLOCKED yok): '$task'. Log: $logfile"
  sed -i "${lineno}s/\[ \]/[?]/" "$TODO"
  echo ">> Bitti (belirsiz sonuç). Durum: $TODO"; exit 3
fi

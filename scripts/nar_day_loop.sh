#!/usr/bin/env bash
# 地方: 10分おきのオッズ更新を1つのジョブの中で回す(定期実行が間引かれて動かないため。11/16)
set -u
END=$(( $(date +%s) + ${LOOP_MINUTES:-330} * 60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  H=$(TZ=Asia/Tokyo date +%H)
  if [ "$H" -ge 22 ]; then echo "22時を過ぎたので終了"; break; fi
  DATE=$(TZ=Asia/Tokyo date +%Y-%m-%d)
  echo "=== $(TZ=Asia/Tokyo date +%H:%M) 更新 ==="
  git pull -q --rebase -X theirs || { git rebase --abort; git fetch -q origin main; git reset -q --hard origin/main; }
  (cd scraper && python rescrape_near_deadline.py --date "$DATE" --window-min 10) || echo "[WARN] 再取得に失敗"
  JSONL="scraper/scraped_data/${DATE}_racecards_raw.jsonl"
  if [ -f "$JSONL" ]; then
    (cd model && python predict.py --input "../$JSONL") || echo "[WARN] 予想に失敗"
    mkdir -p docs/odds_history
    gh release download nar-odds --pattern "odds_${DATE}.csv" --dir docs/odds_history --clobber 2>/dev/null || true
    python pipeline/nar_odds_snapshot.py --date "$DATE" --window-min 120 || true
    [ -f "docs/odds_history/odds_${DATE}.csv" ] && gh release upload nar-odds "docs/odds_history/odds_${DATE}.csv" --clobber || true
    (cd model && python generate_dashboard.py --date "$DATE") || echo "[WARN] ダッシュボードに失敗"
    git add scraper/scraped_data/ docs/
    if ! git diff --cached --quiet; then
      git -c user.name="keiba-ai-bot" -c user.email="bot@example.com" commit -q -m "オッズ更新: $(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M')"
      for i in 1 2 3 4; do git push -q && break; git fetch -q origin main; git merge -X ours --no-edit -q origin/main || { git merge --abort; sleep 5; }; done
    fi
  fi
  sleep 540
done
# まだ22時前ならもう一度起動する(GITHUB_TOKEN の workflow_dispatch は新しい実行を作れる)
if [ "$(TZ=Asia/Tokyo date +%H)" -lt 21 ]; then gh workflow run nar_day_loop.yml && echo "次の回を起動"; fi

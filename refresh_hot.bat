@echo off
chcp 65001 >nul
cd /d E:\矿_news
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo ===== %date% %time% 热榜每日刷新开始 ===== >> logs\hot_refresh.log
python -m crawler.hot --once >> logs\hot_refresh.log 2>&1
python -m tools.social_refresh >> logs\hot_refresh.log 2>&1
python -m tools.clean_article_titles >> logs\hot_refresh.log 2>&1
python -c "from site_build.builder import main; main()" >> logs\hot_refresh.log 2>&1
python -m tools.push_hot >> logs\hot_refresh.log 2>&1
echo ===== %date% %time% 热榜每日刷新完成 ===== >> logs\hot_refresh.log

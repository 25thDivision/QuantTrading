#!/usr/bin/env bash
# systemd 유닛 복사식 배포 (DECISIONS.md 결정 8, CLAUDE.md PART F).
#   deploy/systemd/ 의 *.service *.timer *.slice 를 /etc/systemd/system/ 에 복사(sudo cp) → daemon-reload.
#   심볼릭 링크 금지 (저장소 상태와 무관하게 부팅·재시작이 되어야 무인 복구 사슬이 유지됨).
#   restart 는 하지 않는다: 타이머 구동 서비스라 다음 예약 실행부터 새 정의가 적용된다.
#   즉시 재시작이 필요하면 사람이 명시적으로 `sudo systemctl restart <unit>` 를 실행한다.
# 사용: scripts/deploy_units.sh   (저장소 어느 위치에서 실행해도 됨)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src_dir="${repo_root}/deploy/systemd"
dst_dir="/etc/systemd/system"

if [[ ! -d "${src_dir}" ]]; then
    echo "원본 디렉터리가 없습니다: ${src_dir}" >&2
    exit 1
fi

shopt -s nullglob
units=("${src_dir}"/*.service "${src_dir}"/*.timer "${src_dir}"/*.slice)
shopt -u nullglob

if [[ ${#units[@]} -eq 0 ]]; then
    echo "배포할 유닛 파일이 없습니다: ${src_dir}/*.service|*.timer|*.slice" >&2
    exit 1
fi

for unit in "${units[@]}"; do
    sudo cp -- "${unit}" "${dst_dir}/$(basename "${unit}")"
done
sudo systemctl daemon-reload

echo "복사 완료 → ${dst_dir} (daemon-reload 실행, restart 없음):"
for unit in "${units[@]}"; do
    echo "  $(basename "${unit}")"
done

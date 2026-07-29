#!/usr/bin/env bash
# Isolated operator smoke. Reads credentials only from a root-owned env file.
set -euo pipefail

ENV_FILE="${1:-/etc/recording-agent/synology-smoke.env}"

if [[ ! -r "${ENV_FILE}" ]]; then
  echo "ERROR: unreadable env file: ${ENV_FILE}" >&2
  exit 1
fi

read_env() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" | tail -n 1 | tr -d '\r')"
  if [[ "${value}" =~ ^\".*\"$ || "${value}" =~ ^\'.*\'$ ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

SYNOLOGY_BASE_URL="$(read_env SYNOLOGY_BASE_URL)"
SYNOLOGY_USER="$(read_env SYNOLOGY_USER)"
SYNOLOGY_PASS="$(read_env SYNOLOGY_PASS)"
SYNOLOGY_DEVICE_ID="$(read_env SYNOLOGY_DEVICE_ID)"
TEST_ROOT="$(read_env SYNOLOGY_TEST_ROOT)"
TEST_ROOT="${TEST_ROOT:-/home/Recruiting-E/3. Interviews internal/Flutter}"
for required in SYNOLOGY_BASE_URL SYNOLOGY_USER SYNOLOGY_PASS; do
  if [[ -z "${!required:-}" ]]; then
    echo "ERROR: missing ${required}" >&2
    exit 1
  fi
done

base_url="${SYNOLOGY_BASE_URL%/}"
entry_url="${base_url}/webapi/entry.cgi"
query_url="${base_url}/webapi/query.cgi"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid | tr -d '-')"
work_dir="${TEST_ROOT}/recording-agent-copymove-smoke-${run_id}"
source_dir="${work_dir}/source"
target_dir="${work_dir}/target"
filename="marker-${run_id}.txt"
marker_name=".${filename}.recording-agent-owner.json"
untouched_name="untouched-${run_id}.txt"
source_file="${source_dir}/${filename}"
source_marker="${source_dir}/${marker_name}"
untouched_source="${source_dir}/${untouched_name}"
target_file="${target_dir}/${filename}"
target_marker="${target_dir}/${marker_name}"
untouched_target="${target_dir}/${untouched_name}"
payload="recording-agent-copymove-smoke:${run_id}"
marker_payload="{\"recording_agent_smoke\":\"${run_id}\"}"
untouched_payload="recording-agent-copymove-untouched:${run_id}"
tmp_dir="$(mktemp -d)"
payload_file="${tmp_dir}/${filename}"
marker_file="${tmp_dir}/${marker_name}"
untouched_file="${tmp_dir}/${untouched_name}"
sid=""

cleanup_local() {
  rm -rf "${tmp_dir}"
}
trap cleanup_local EXIT

require_success() {
  local response="$1"
  if [[ "$(jq -r '.success // false' <<<"${response}")" != "true" ]]; then
    echo "ERROR: Synology API step failed: ${step:-unknown}" >&2
    jq -c '{success,error}' <<<"${response}" >&2
    exit 1
  fi
}

api_post() {
  curl --fail --silent --show-error --request POST "${entry_url}" "$@"
}

api_get() {
  curl --fail --silent --show-error --get "${entry_url}" "$@"
}

delete_test_tree() {
  local response
  response="$(api_get \
    --data-urlencode 'api=SYNO.FileStation.Delete' \
    --data-urlencode 'version=2' \
    --data-urlencode 'method=delete' \
    --data-urlencode "path=$(jq -cn --arg path "${work_dir}" '$path')" \
    --data-urlencode 'recursive=true' \
    --data-urlencode "_sid=${sid}")" || return 1
  require_success "${response}"
}

logout() {
  if [[ -n "${sid}" ]]; then
    api_get \
      --data-urlencode 'api=SYNO.API.Auth' \
      --data-urlencode 'version=6' \
      --data-urlencode 'method=logout' \
      --data-urlencode 'session=FileStation' \
      --data-urlencode "_sid=${sid}" >/dev/null || true
  fi
}
trap logout EXIT

info="$(curl --fail --silent --show-error --get "${query_url}" \
  --data-urlencode 'api=SYNO.API.Info' \
  --data-urlencode 'version=1' \
  --data-urlencode 'method=query' \
  --data-urlencode 'query=SYNO.FileStation.CopyMove,SYNO.FileStation.Sharing')"
step='API capability query'
require_success "${info}"
copy_version="$(jq -r '.data["SYNO.FileStation.CopyMove"].maxVersion // empty' <<<"${info}")"
if [[ ! "${copy_version}" =~ ^[0-9]+$ ]]; then
  echo 'ERROR: DSM does not advertise SYNO.FileStation.CopyMove' >&2
  exit 1
fi
if [[ "$(jq -r '.data["SYNO.FileStation.Sharing"].maxVersion // empty' <<<"${info}")" == "" ]]; then
  echo 'ERROR: DSM does not advertise SYNO.FileStation.Sharing' >&2
  exit 1
fi

login_args=(
  --data-urlencode 'api=SYNO.API.Auth'
  --data-urlencode 'version=6'
  --data-urlencode 'method=login'
  --data-urlencode "account=${SYNOLOGY_USER}"
  --data-urlencode "passwd=${SYNOLOGY_PASS}"
  --data-urlencode 'session=FileStation'
  --data-urlencode 'format=sid'
)
if [[ -n "${SYNOLOGY_DEVICE_ID:-}" ]]; then
  login_args+=(--data-urlencode "device_id=${SYNOLOGY_DEVICE_ID}")
fi
login="$(api_get "${login_args[@]}")"
step='SID login'
require_success "${login}"
sid="$(jq -r '.data.sid // empty' <<<"${login}")"
if [[ -z "${sid}" ]]; then
  echo 'ERROR: DSM login returned no SID' >&2
  exit 1
fi

for path in "${TEST_ROOT}" "${work_dir}" "${source_dir}" "${target_dir}"; do
  if [[ "${path}" == "${TEST_ROOT}" ]]; then
    continue
  fi
  parent="${path%/*}"
  name="${path##*/}"
  response="$(api_post \
    --data-urlencode 'api=SYNO.FileStation.CreateFolder' \
    --data-urlencode 'version=2' \
    --data-urlencode 'method=create' \
    --data-urlencode "folder_path=${parent}" \
    --data-urlencode "name=${name}" \
    --data-urlencode 'force_parent=false' \
    --data-urlencode "_sid=${sid}")"
  step="create test folder ${name}"
  require_success "${response}"
done

printf '%s' "${payload}" >"${payload_file}"
printf '%s' "${marker_payload}" >"${marker_file}"
printf '%s' "${untouched_payload}" >"${untouched_file}"
for upload_file in "${payload_file}" "${marker_file}" "${untouched_file}"; do
  upload_url="${entry_url}?api=SYNO.FileStation.Upload&version=2&method=upload&_sid=$(jq -rn --arg sid "${sid}" '$sid | @uri')"
  response="$(curl --fail --silent --show-error --request POST "${upload_url}" \
    --form "path=${source_dir}" \
    --form 'create_parents=false' \
    --form 'overwrite=false' \
    --form "file=@${upload_file};type=application/octet-stream")"
  step='upload generated test file'
  require_success "${response}"
done

copy_move_one() {
  local source="$1"
  local copy_response task_id status_response status=''
  copy_response="$(api_get \
    --data-urlencode 'api=SYNO.FileStation.CopyMove' \
    --data-urlencode "version=${copy_version}" \
    --data-urlencode 'method=start' \
    --data-urlencode "path=$(jq -cn --arg path "${source}" '[ $path ]')" \
    --data-urlencode "dest_folder_path=$(jq -cn --arg path "${target_dir}" '$path')" \
    --data-urlencode 'remove_src=true' \
    --data-urlencode 'overwrite=false' \
    --data-urlencode 'accurate_progress=true' \
    --data-urlencode "_sid=${sid}")"
  step='CopyMove start'
  require_success "${copy_response}"
  task_id="$(jq -r '.data.taskid // empty' <<<"${copy_response}")"
  if [[ -z "${task_id}" ]]; then
    echo 'ERROR: CopyMove start returned no task id' >&2
    exit 1
  fi
  for _ in $(seq 1 30); do
    status_response="$(api_get \
      --data-urlencode 'api=SYNO.FileStation.CopyMove' \
      --data-urlencode "version=${copy_version}" \
      --data-urlencode 'method=status' \
      --data-urlencode "taskid=$(jq -cn --arg task_id "${task_id}" '$task_id')" \
      --data-urlencode "_sid=${sid}")"
    step='CopyMove status'
    if [[ "$(jq -r '.success // false' <<<"${status_response}")" != 'true' ]]; then
      if [[ "$(jq -r '.error.code // empty' <<<"${status_response}")" == '599' ]]; then
        status='finished'
        break
      fi
      require_success "${status_response}"
    fi
    status="$(jq -r '.data.status // .data.finished // empty' <<<"${status_response}")"
    if [[ "$(jq -r '.data.has_fail // false' <<<"${status_response}")" == 'true' ]]; then
      echo "ERROR: CopyMove task reported failure; test tree preserved: ${work_dir}" >&2
      exit 1
    fi
    if [[ "${status}" == 'finished' || "${status}" == 'true' ]]; then
      return
    fi
    sleep 1
  done
  if [[ "${status}" != 'finished' && "${status}" != 'true' ]]; then
    echo "ERROR: CopyMove task did not finish within 30 seconds; test tree preserved: ${work_dir}" >&2
    exit 1
  fi
}

copy_move_one "${source_file}"
copy_move_one "${source_marker}"

get_info() {
  api_get \
    --data-urlencode 'api=SYNO.FileStation.List' \
    --data-urlencode 'version=2' \
    --data-urlencode 'method=getinfo' \
    --data-urlencode "path=$(jq -cn --arg path "$1" '[ $path ]')" \
    --data-urlencode 'additional=["size"]' \
    --data-urlencode "_sid=${sid}"
}
path_exists() {
  local path="$1"
  local response
  response="$(get_info "${path}")"
  jq -e --arg path "${path}" '
    .success == true
    and (.data.files | type == "array")
    and any(
      .data.files[]?;
      .path == $path and ((.size // .additional.size // null) | type == "number")
    )
  ' <<<"${response}" >/dev/null
}
target_info="$(get_info "${target_file}")"
target_marker_info="$(get_info "${target_marker}")"
step='target verification'
require_success "${target_info}"
require_success "${target_marker_info}"
target_size="$(jq -r '.data.files[0].size // .data.files[0].additional.size // -1' <<<"${target_info}")"
target_marker_size="$(jq -r '.data.files[0].size // .data.files[0].additional.size // -1' <<<"${target_marker_info}")"
if [[ "${target_size}" != "${#payload}" ]] || [[ "${target_marker_size}" != "${#marker_payload}" ]]; then
  echo "INFO: target response keys: $(jq -c '.data.files[0] | keys' <<<"${target_info}")" >&2
  echo "ERROR: target size mismatch: file ${target_size}/${#payload}, marker ${target_marker_size}/${#marker_payload}" >&2
  echo "ERROR: target size or marker size mismatch; test tree preserved: ${work_dir}" >&2
  exit 1
fi
source_remained=false
for source in "${source_file}" "${source_marker}"; do
  if path_exists "${source}"; then
    source_remained=true
  fi
done

if [[ "${source_remained}" == 'true' ]]; then
  # This DSM accepts remove_src but performs a copy. Delete is allowed only after
  # destination and owner-marker verification above; never before it.
  for source in "${source_file}" "${source_marker}"; do
    delete_source_response="$(api_get \
      --data-urlencode 'api=SYNO.FileStation.Delete' \
      --data-urlencode 'version=2' \
      --data-urlencode 'method=delete' \
      --data-urlencode "path=$(jq -cn --arg path "${source}" '$path')" \
      --data-urlencode 'recursive=false' \
      --data-urlencode "_sid=${sid}")"
    step='verified source deletion fallback'
    require_success "${delete_source_response}"
    if path_exists "${source}"; then
      echo "ERROR: source remains after verified deletion fallback: ${source##*/}; test tree preserved: ${work_dir}" >&2
      exit 1
    fi
  done
  move_mode='CopyMove copy plus verified source delete fallback'
else
  move_mode='CopyMove native move'
fi
if ! path_exists "${untouched_source}" || path_exists "${untouched_target}"; then
  echo "ERROR: selective move altered an unselected source file; test tree preserved: ${work_dir}" >&2
  exit 1
fi

share_response="$(api_post \
  --data-urlencode 'api=SYNO.FileStation.Sharing' \
  --data-urlencode 'version=3' \
  --data-urlencode 'method=create' \
  --data-urlencode "path=$(jq -cn --arg path "${target_file}" '[ $path ]')" \
  --data-urlencode 'date_expired=-1' \
  --data-urlencode 'date_available=0' \
  --data-urlencode "_sid=${sid}")"
require_success "${share_response}"

delete_test_tree
echo "PASS: ${move_mode}; CopyMove v${copy_version}, selected file+marker moved, unselected source file retained, public link created, generated test tree removed."

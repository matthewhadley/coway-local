#!/usr/bin/env bash
# Sets up a Coway fan that takes its Wi-Fi settings over its own hotspot
# instead of Bluetooth, such as the Airmega 250S (AP-1720G) with product code
# 02F9R. It sends the setup page's P001/P002 messages over TCP, so the fan
# enrolls with Home Assistant as one set up from the page does.
# HOTSPOT_SETUP.md at the repository root describes the exchange.
#
# The setup page shows the command to run, with the setup link in it:
#   curl -fsSL https://scottjg.github.io/coway-local/v1/softap.sh | bash -s -- 'SETUP_LINK'
# Run it on your usual network: the fan's hotspot has no internet.
#
# Needs bash 3.2 or newer (its /dev/tcp), openssl and od, so it runs on a Mac
# or Linux as they come.

usage() {
  cat <<'EOF'
Usage: softap.sh [options] SETUP_LINK

SETUP_LINK is the setup link from Home Assistant, including its #setup= part.
Start on your usual network; the script asks you to join the fan's hotspot.

Options:
  --name NAME   name for the fan in Home Assistant (default: Coway + end of its MAC)
  --host IP     the fan's address on its hotspot (default: 192.168.12.101)
  --mac MAC     the fan's MAC, if ARP cannot find it
  --no-open     print Home Assistant's return link instead of opening it
EOF
}

SCAN_PORT=5001
SETUP_PORT=5040

fail() {
  printf 'coway-softap: %s\n' "$*" >&2
  exit 1
}

# Prompts read the terminal when the script arrives on stdin, as with
# curl | bash, and stdin when it is run from a file.
ask() {
  printf '%s' "$1"
  IFS= read -r -u 4 REPLY || fail 'input ended before an answer'
}

# bash 3.2's read -s only stops the echo on stdin, so the read takes the
# prompt's input as its stdin rather than through -u.
ask_hidden() {
  printf '%s' "$1"
  IFS= read -r -s REPLY <&4 || fail 'input ended before an answer'
  printf '\n'
}

# Writes the bytes of one protobuf varint.
varint() {
  local n=$1 out=''
  while (( n > 127 )); do
    out+=$(printf '\\%03o' $(( (n & 127) | 128 )))
    n=$(( n >> 7 ))
  done
  out+=$(printf '\\%03o' "$n")
  # shellcheck disable=SC2059 # the format is only octal escapes, built above
  printf "$out"
}

# Writes a length-delimited protobuf field from a string.
field() {
  local length
  length=$(printf '%s' "$2" | wc -c | tr -d ' ')
  (( length )) || return 0
  varint $(( $1 * 8 + 2 ))
  varint "$length"
  printf '%s' "$2"
}

# Writes a length-delimited protobuf field from octal escapes, as the scan's
# SSIDs are kept so any byte survives.
field_escaped() {
  varint $(( $1 * 8 + 2 ))
  varint "$3"
  # shellcheck disable=SC2059 # the format is only octal escapes
  printf "$2"
}

b64url() {
  openssl base64 -A | tr '+/' '-_' | tr -d '='
}

# Lower-case ASCII letters, as the setup page's randomLetters gives.
random_letters() {
  # shellcheck disable=SC2018 # ASCII a-z is wanted, not the locale's letters
  LC_ALL=C tr -dc 'a-z' </dev/urandom | head -c "$1"
}

hex_of() {
  printf '%s' "$1" | od -An -v -tx1 | tr -d ' \n'
}

# Reads one byte from fd $1 into BYTE, waiting up to $2 seconds. Returns 1 at
# the end of the stream and 2 on timeout.
read_byte() {
  local c status
  IFS= read -r -d '' -n 1 -t "$2" -u "$1" c
  status=$?
  (( status > 128 )) && return 2
  if [[ -z $c ]]; then
    (( status == 0 )) || return 1
    BYTE=0
  else
    printf -v BYTE '%d' "'$c"
    (( BYTE < 0 )) && BYTE=$(( BYTE + 256 ))
  fi
  return 0
}

read_varint() {
  local value=0 shift=0
  while :; do
    read_byte "$1" "$2" || return 1
    value=$(( value | (BYTE & 127) << shift ))
    (( BYTE & 128 )) || break
    shift=$(( shift + 7 ))
    (( shift < 35 )) || return 1
  done
  VARINT=$value
}

# Reads the fan's reply to P001 or P002: a bare protobuf message of cmd (1),
# ok (2) and an optional code (3), with no length prefix.
read_status() {
  local fd=$1 what=$2 tag
  STATUS_CMD='' STATUS_OK='' STATUS_CODE=0
  while [[ -z $STATUS_CMD || -z $STATUS_OK ]]; do
    read_byte "$fd" 15 || fail "no reply from the fan while $what"
    tag=$BYTE
    read_varint "$fd" 15 || fail "a malformed reply from the fan while $what"
    case $tag in
      8) STATUS_CMD=$VARINT ;;
      16) STATUS_OK=$VARINT ;;
      24) STATUS_CODE=$VARINT ;;
      *) fail "an unexpected reply from the fan while $what" ;;
    esac
  done
  # The code comes after cmd and ok when the fan sends one.
  if read_byte "$fd" 1; then
    (( BYTE == 24 )) && read_varint "$fd" 1 && STATUS_CODE=$VARINT
  fi
}

# The link's JSON comes from Coway Local's setup_url: compact, and its values
# have nothing JSON would escape, as read_setup checks each against a pattern.
json_string() {
  local pattern="\"$1\":\"([^\"\\\\]*)\""
  [[ $SETUP_JSON =~ $pattern ]] && printf '%s' "${BASH_REMATCH[1]}"
}

json_number() {
  local pattern="\"$1\":([0-9]+)[,}]"
  [[ $SETUP_JSON =~ $pattern ]] && printf '%s' "${BASH_REMATCH[1]}"
}

# Decodes and checks the setup link as the setup page's validateBundle does.
read_setup() {
  local link=$1 encoded padded now ca_host ca_port cert_host cert_port
  [[ $link == *setup=* ]] || fail 'the setup link has no #setup= part, which holds the setup details'
  encoded=${link##*setup=}
  encoded=${encoded%%&*}
  [[ $encoded =~ ^[A-Za-z0-9_-]+$ && ${#encoded} -le 4096 ]] || fail 'invalid setup link'
  padded=$(printf '%s' "$encoded" | tr -- '-_' '+/')
  while (( ${#padded} % 4 )); do padded+='='; done
  SETUP_JSON=$(printf '%s\n' "$padded" | openssl base64 -d -A) || fail 'invalid setup link'

  [[ $(json_number v) == 1 ]] || fail 'this script does not match your Coway Local version; create a new setup link in Home Assistant'
  CERT_TOKEN=$(json_string certToken)
  CA_URL=$(json_string caUrl)
  CERT_URL=$(json_string certSvrUrl)
  RETURN_URL=$(json_string returnUrl)
  EXPIRES_AT=$(json_number expiresAt)
  [[ $CERT_TOKEN =~ ^[A-Za-z0-9_-]{32}$ && -n $EXPIRES_AT ]] || fail 'invalid setup link; create a new one in Home Assistant'

  [[ $CA_URL =~ ^http://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)/ca\.pem$ ]] || fail 'invalid local server address in the setup link'
  ca_host=${BASH_REMATCH[1]} ca_port=${BASH_REMATCH[2]}
  [[ $CERT_URL =~ ^https://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)/n$ ]] || fail 'invalid local server address in the setup link'
  cert_host=${BASH_REMATCH[1]} cert_port=${BASH_REMATCH[2]}
  if [[ $ca_host != "$cert_host" || $ca_port == "$cert_port" ]] \
    || (( ca_port < 1024 || ca_port > 65535 || cert_port < 1024 || cert_port > 65535 )); then
    fail 'invalid local server addresses in the setup link'
  fi
  [[ $RETURN_URL =~ ^(https?://[^/?#@]+)/api/coway_local/provisioning/return\?(flow_id=[a-f0-9]{32}&state=[A-Za-z0-9_-]{32}|state=[A-Za-z0-9_-]{32}&flow_id=[a-f0-9]{32})$ ]] \
    || fail 'invalid Home Assistant return address; create a new setup link'
  HA_ORIGIN=${BASH_REMATCH[1]}
  HA_HOST=$ca_host

  now=$(date +%s)
  (( EXPIRES_AT / 1000 > now )) || fail 'this setup link expired; create a new one in Home Assistant'
}

check_expiry() {
  (( EXPIRES_AT / 1000 > $(date +%s) )) || fail 'the setup link expired; create a new one in Home Assistant'
}

# Waits up to $3 seconds for a TCP connection to succeed, without hanging on
# an address with no route.
reachable() {
  local pid i
  ( exec 5<>"/dev/tcp/$1/$2" ) 2>/dev/null &
  pid=$!
  for (( i = 0; i < $3 * 4; i++ )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      return
    fi
    sleep 0.25
  done
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  return 1
}

fan_mac() {
  local line octets mac=''
  if [[ -n $OPT_MAC ]]; then
    mac=$(printf '%s' "$OPT_MAC" | tr -d ':-' | tr 'a-f' 'A-F')
  else
    # arp exits non-zero when it lacks an entry; Linux may only have ip.
    line=$( (arp -an 2>/dev/null; ip neigh show 2>/dev/null) | grep -F -m 1 -e "($1)" -e "$1 ")
    if [[ $line =~ ([0-9a-fA-F]{1,2}(:[0-9a-fA-F]{1,2}){5}) ]]; then
      # macOS drops leading zeros: 84:72:7:62:94:f3.
      IFS=: read -r -a octets <<<"${BASH_REMATCH[1]}"
      for octet in "${octets[@]}"; do
        (( ${#octet} == 1 )) && octet=0$octet
        mac+=$octet
      done
      mac=$(printf '%s' "$mac" | tr 'a-f' 'A-F')
    fi
  fi
  [[ $mac =~ ^[0-9A-F]{12}$ ]] || fail "cannot find the fan's MAC for $1; pass it with --mac"
  FAN_MAC=$mac
}

# Asks the fan for the networks it can see, reading its MAC while connected,
# when ARP is sure to have it.
scan() {
  local host=$1 deadline hex='' count=0 h
  deadline=$(( $(date +%s) + 60 ))
  until reachable "$host" "$SCAN_PORT" 3; do
    (( $(date +%s) < deadline )) || fail "no answer from $host:$SCAN_PORT. Is this computer on the fan's hotspot, and the fan in setup mode?"
    printf '.'
    sleep 2
  done
  exec 3<>"/dev/tcp/$host/$SCAN_PORT" || fail "cannot connect to $host:$SCAN_PORT"
  fan_mac "$host"
  printf 'AT*ICT*SCAN\r' >&3
  SCAN=()
  while :; do
    read_byte 3 25
    case $? in
      1) break ;;
      2) fail 'timed out waiting for the Wi-Fi scan' ;;
    esac
    SCAN[count]=$BYTE
    count=$(( count + 1 ))
    printf -v h '%02x' "$BYTE"
    hex+=$h
    (( count <= 65536 )) || fail 'the Wi-Fi scan is too large'
    [[ ${hex: -12} == 5b4f4b5d0d0a ]] && break
  done
  exec 3>&-
  SCAN_HEX=$hex
  [[ ${hex:0:32} == $(hex_of '*ICT*SCANRESULT:') ]] || fail 'unexpected Wi-Fi scan response'
}

# Lists the scan's 2.4 GHz networks, strongest first, into NET_* arrays.
parse_scan() {
  local offset length i h rssi ssid lines='' line
  NET_SSID=() NET_LEN=() NET_BSSID=() NET_RSSI=() NET_SECURE=() NET_CHANNEL=()
  local -a ssid_e=() ssid_l=() bssid=() rssis=() secure=() channel=()
  local n=0
  for (( offset = 16; offset + 48 <= ${#SCAN[@]}; offset += 48 )); do
    [[ ${SCAN_HEX:offset*2:8} == 5b4f4b5d ]] && break
    length=$(( SCAN[offset + 2] | SCAN[offset + 3] << 8 ))
    (( length > 0 && length <= 32 )) || continue
    (( SCAN[offset + 47] <= 14 )) || continue
    ssid=''
    for (( i = 0; i < length; i++ )); do
      printf -v h '\\%03o' "${SCAN[offset + 4 + i]}"
      ssid+=$h
    done
    rssi=$(( SCAN[offset + 42] | SCAN[offset + 43] << 8 | SCAN[offset + 44] << 16 | SCAN[offset + 45] << 24 ))
    (( rssi >= 2147483648 )) && rssi=$(( rssi - 4294967296 ))
    ssid_e[n]=$ssid ssid_l[n]=$length rssis[n]=$rssi
    bssid[n]=$(printf '%s' "${SCAN_HEX:(offset + 36)*2:12}" | tr 'a-f' 'A-F')
    secure[n]=${SCAN[offset + 46]} channel[n]=${SCAN[offset + 47]}
    lines+="$rssi $n"$'\n'
    n=$(( n + 1 ))
  done
  (( n )) || fail 'the fan found no 2.4 GHz networks'
  i=0
  while read -r rssi line; do
    [[ -n $line ]] || continue
    NET_SSID[i]=${ssid_e[line]} NET_LEN[i]=${ssid_l[line]} NET_BSSID[i]=${bssid[line]}
    NET_RSSI[i]=${rssis[line]} NET_SECURE[i]=${secure[line]} NET_CHANNEL[i]=${channel[line]}
    i=$(( i + 1 ))
  done < <(printf '%s' "$lines" | sort -k1,1nr -k2,2n)
}

# A network's SSID for display, without control characters.
ssid_text() {
  # shellcheck disable=SC2059 # SSIDs are kept as octal escapes
  printf "${NET_SSID[$1]}" | tr -d '\000-\037\177'
}

choose_network() {
  local i bssid open
  for (( i = 0; i < ${#NET_SSID[@]}; i++ )); do
    bssid=$(printf '%s' "${NET_BSSID[i]}" | sed 's/../&:/g; s/:$//')
    open=''
    (( NET_SECURE[i] )) || open='  (open)'
    printf '  %2d  %-32s  ch %2d  %4d dBm  %s%s\n' $(( i + 1 )) "$(ssid_text "$i")" \
      "${NET_CHANNEL[i]}" "${NET_RSSI[i]}" "$bssid" "$open"
  done
  ask 'Network [1]: '
  [[ -n $REPLY ]] || REPLY=1
  if ! [[ $REPLY =~ ^[0-9]+$ ]] || (( REPLY < 1 || REPLY > ${#NET_SSID[@]} )); then
    fail "no network $REPLY"
  fi
  CHOSEN=$(( REPLY - 1 ))
}

# The fields the setup page's wifiConfig sends, in field order.
config_proto() {
  printf '\010\002'
  field_escaped 2 "${NET_SSID[CHOSEN]}" "${NET_LEN[CHOSEN]}"
  field 3 "$PASSWORD"
  field 4 "${NET_BSSID[CHOSEN]}"
  printf '\050\001'
  field 10 "$FAN_MAC"
  field 11 "$CA_URL"
  field 12 "$CERT_URL/$(printf '%s' "$FAN_NAME" | b64url)"
  field 13 "$CERT_TOKEN"
  field 14 "LOCAL0$FAN_MAC"
}

provision() {
  local host=$1 key iv key_hex iv_hex p001 p002
  key=$(random_letters 20)
  iv=$(random_letters 16)
  (( ${#key} == 20 && ${#iv} == 16 )) || fail 'cannot read random bytes'
  key_hex=$(hex_of "$key$FAN_MAC")
  iv_hex=$(hex_of "$iv")
  # openssl enc applies PKCS#7 padding, as Web Crypto's AES-CBC does.
  p002=$( { printf '%s' "$iv"; config_proto | openssl enc -aes-256-cbc -K "$key_hex" -iv "$iv_hex"; } | openssl base64 -A) \
    || fail 'cannot encrypt the settings'

  p001=$(printf 'P001\010\001'; field 2 "$(printf '%s' "$key" | openssl base64 -A)")

  # Each message goes in one write, as the Coway app and the Node version sent them.
  exec 3<>"/dev/tcp/$host/$SETUP_PORT" || fail "cannot connect to $host:$SETUP_PORT"
  printf '%s' "$p001" >&3
  read_status 3 'waiting for the fan to accept the setup key'
  printf 'Setup key: cmd %s, ok %s, code %s\n' "$STATUS_CMD" "$STATUS_OK" "$STATUS_CODE"
  # The code varies; a 02F9R has answered 61, 2, 5 and 0.
  [[ $STATUS_CMD == 1 && $STATUS_OK == 1 ]] || fail 'the fan rejected the setup key'
  printf 'P002%s' "$p002" >&3
  read_status 3 'waiting for the fan to accept the settings'
  printf 'Settings: cmd %s, ok %s, code %s\n' "$STATUS_CMD" "$STATUS_OK" "$STATUS_CODE"
  [[ $STATUS_CMD == 2 && $STATUS_OK == 1 ]] || fail 'the fan rejected the settings'
  exec 3>&-
}

# The fan leaves hotspot mode once it has the settings, and this computer
# should rejoin its usual network. Home Assistant answering means it has.
wait_for_home_assistant() {
  local deadline
  deadline=$(( $(date +%s) + 180 ))
  while (( $(date +%s) < deadline )); do
    curl -ks -o /dev/null --max-time 3 "$HA_ORIGIN" && return 0
    sleep 3
  done
  return 1
}

open_link() {
  if [[ $(uname) == Darwin ]]; then
    open "$1"
  elif [[ -n ${DISPLAY:-}${WAYLAND_DISPLAY:-} ]] && command -v xdg-open >/dev/null; then
    xdg-open "$1" >/dev/null 2>&1
  else
    return 1
  fi
}

main() {
  export LC_ALL=C
  local host=192.168.12.101 link='' no_open=''
  OPT_MAC='' FAN_NAME=''
  while (( $# )); do
    case $1 in
      --name) FAN_NAME=${2-}; shift 2 || fail '--name needs a value' ;;
      --host) host=${2-}; shift 2 || fail '--host needs a value' ;;
      --mac) OPT_MAC=${2-}; shift 2 || fail '--mac needs a value' ;;
      --no-open) no_open=1; shift ;;
      -h|--help) usage; return 0 ;;
      -*) fail "unknown option $1" ;;
      *) [[ -z $link ]] || fail 'expected one setup link'; link=$1; shift ;;
    esac
  done
  [[ -n $link ]] || { usage >&2; exit 1; }
  for tool in openssl od curl; do
    command -v "$tool" >/dev/null || fail "needs $tool"
  done

  if [[ -n ${BASH_SOURCE[0]:-} && -f ${BASH_SOURCE[0]} ]]; then
    exec 4<&0
  else
    exec 4</dev/tty || fail 'needs a terminal to ask questions'
  fi

  read_setup "$link"
  printf 'Home Assistant: %s; the setup link expires in %d minutes.\n' "$HA_HOST" $(( (EXPIRES_AT / 1000 - $(date +%s)) / 60 ))
  printf '\nPut the fan in Wi-Fi setup mode. On the Airmega 250S, turn it on, then hold\n'
  printf 'Filter Reset and Wi-Fi together for 3 seconds, until the Wi-Fi light blinks.\n'
  ask "Then join this computer to the fan's Wi-Fi hotspot and press Return: "

  printf 'Asking the fan at %s for nearby networks...' "$host"
  scan "$host"
  printf '\n'
  parse_scan
  [[ -n $FAN_NAME ]] || FAN_NAME="Coway ${FAN_MAC:6}"
  if (( ${#FAN_NAME} > 80 )) || [[ $FAN_NAME =~ [[:cntrl:]] ]]; then
    fail 'the name must be 1-80 characters without control characters'
  fi
  printf 'Fan MAC %s, named "%s"\n' "$(printf '%s' "$FAN_MAC" | sed 's/../&:/g; s/:$//')" "$FAN_NAME"

  choose_network
  PASSWORD=''
  if (( NET_SECURE[CHOSEN] )); then
    if [[ -n ${COWAY_WIFI_PASSWORD:-} ]]; then
      PASSWORD=$COWAY_WIFI_PASSWORD
    else
      ask_hidden "Password for $(ssid_text "$CHOSEN"): "
      PASSWORD=$REPLY
    fi
    length=$(printf '%s' "$PASSWORD" | wc -c | tr -d ' ')
    (( length >= 8 && length <= 63 )) || fail 'the Wi-Fi password must be 8-63 bytes'
  fi

  check_expiry
  provision "$host"
  printf 'The fan has its settings and should now leave hotspot mode and join your Wi-Fi.\n'

  if [[ -n $no_open ]]; then
    printf 'Once this computer is back on your network, open:\n%s\n' "$RETURN_URL"
    return 0
  fi
  printf 'Rejoin your usual network. Waiting to reach Home Assistant...\n'
  wait_for_home_assistant || fail "Home Assistant is not reachable. Rejoin your network, then open:
$RETURN_URL"
  if open_link "$RETURN_URL"; then
    printf 'Opened Home Assistant, which will wait for the fan to connect.\n'
  else
    printf 'Open this link to finish in Home Assistant:\n%s\n' "$RETURN_URL"
  fi
}

# Everything runs from here, so bash has read the whole script before it
# starts, even when the script arrives on stdin.
main "$@"

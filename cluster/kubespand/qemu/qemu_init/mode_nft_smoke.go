package main

import (
	"strconv"
	"strings"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
)

func modeNftSmoke(params map[string]string) {
	levels := params["levels"]
	if levels == "" {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "no levels= on kernel cmdline", Error: "missing levels parameter"})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventBoot, Message: "nft_smoke mode, levels=" + levels})

	anyFail := false
	for _, level := range strings.Split(levels, ",") {
		level = strings.TrimSpace(level)
		if level == "" {
			continue
		}
		levelNum, err := strconv.Atoi(level)
		if err != nil {
			emitEvent(qemu.Event{Type: qemu.EventError, Message: "invalid level " + strconv.Quote(level), Error: err.Error()})
			anyFail = true
			continue
		}
		exitCode := runNftSmokeLevel(levelNum)
		success := exitCode == 0
		if !success {
			anyFail = true
		}
		emitEvent(qemu.Event{Type: qemu.EventProbe, Message: "level " + level, Target: "nft-smoke-" + level, Success: &success})
	}

	if anyFail {
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "some levels failed", Error: "not all nft-smoke levels passed"})
	} else {
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "all levels passed"})
	}
	poweroff()
}

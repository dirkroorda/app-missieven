import sys
import collections

from tf.convert.recorder import Recorder


def combiFeatures(maker):
    combiV = getattr(maker, "combiV", None)
    if combiV is not None:
        return

    A = maker.A
    A.info("Combining features ...")
    api = A.api
    F = api.F
    L = api.L

    combiV = {}
    combiFreqList = {}

    setattr(maker, "combiV", combiV)
    setattr(maker, "combiFreqList", combiFreqList)

    def orNull(x):
        return "" if x is None else x

    kind = {}
    kindFreq = collections.Counter()

    Fisremark = F.isremark.v
    Fisnote = F.isnote.v
    Fisorig = F.isorig.v
    Fisfolio = F.isfolio.v

    for w in F.otype.s("word"):
        k = (
            "r"
            if Fisremark(w)
            else "n"
            if Fisnote(w)
            else "o"
            if Fisorig(w)
            else "f"
            if Fisfolio(w)
            else "?"
        )
        kind[w] = k
        kindFreq[k] += 1

    combiV["kind"] = kind
    combiFreqList["kind"] = kindFreq.items()

    textloc = {}
    textlocFreq = collections.Counter()

    curPage = None
    for ln in F.otype.s("line"):
        pages = L.u(ln, otype="page")
        page = pages[0] if pages else curPage
        curPage = page
        loc = f"{F.n.v(curPage)}:{F.n.v(ln)}"
        textloc[ln] = loc
        textlocFreq[loc] += 1

    combiV["textloc"] = textloc
    combiFreqList["textloc"] = textlocFreq.items()

    date = {}
    dateFreq = collections.Counter()

    Fyear = F.year.v
    Fmonth = F.month.v
    Fday = F.day.v

    for lt in F.otype.s("letter"):
        d = f"{Fyear(lt)}-{Fmonth(lt)}-{Fday(lt)}"
        date[lt] = d
        dateFreq[d] += 1

    combiV["date"] = date
    combiFreqList["date"] = dateFreq.items()


def makeLegends(maker):
    A = maker.A
    combiFeatures(maker)
    combiFreqList = getattr(maker, "combiFreqList")

    api = A.api
    Fs = api.Fs

    C = maker.C
    layerSettings = C.layerSettings

    for (level, layer) in (
        ("word", "kind"),
        ("letter", "date"),
        ("letter", "author"),
        ("letter", "place"),
        ("volume", "number"),
    ):

        info = layerSettings[level]["layers"][layer]
        feature = info["feature"]

        freqList = (
            combiFreqList["kind"]
            if feature == "kind"
            else combiFreqList["textLoc"]
            if feature == "textLoc"
            else combiFreqList["date"]
            if feature == "date"
            else Fs(feature).freqList(nodeTypes={level})
        )
        info["legend"] = sorted(freqList)


def record(maker):
    A = maker.A
    combiFeatures(maker)
    combiV = getattr(maker, "combiV")

    api = A.api
    F = api.F
    Fs = api.Fs
    L = api.L

    C = maker.C
    layerSettings = C.layerSettings

    clientConfig = maker.clientConfig
    typesLower = clientConfig["typesLower"]

    A.indent(reset=True)
    A.info("preparing ... ")

    A.info("start recording")

    up = {}
    recorders = {}
    accumulators = {}
    maker.up = up
    maker.recorders = recorders
    maker.accumulators = accumulators

    afterDefaults = {}

    for (level, typeInfo) in layerSettings.items():
        ti = typeInfo.get("layers", None)
        if ti is None:
            continue

        recorders[level] = {
            layer: Recorder(api) for layer in ti if ti[layer]["pos"] is None
        }
        accumulators[level] = {
            layer: [] for layer in ti if ti[layer]["pos"] is not None
        }

        afterDefaults[level] = typeInfo.get("afterDefault", None)

    def addValue(node):
        returnValue = None

        level = F.otype.v(node)
        typeInfo = layerSettings[level]
        theseLayers = typeInfo.get("layers", {})
        afterDefault = typeInfo.get("afterDefault", None)

        first = True

        for layer in theseLayers:
            info = theseLayers[layer]
            feature = info.get("feature", None)
            afterFeature = info.get("afterFeature", None)
            vMap = info.get("legend", None)
            if type(vMap) is not dict:
                vMap = None
            default = info["default"]
            pos = info["pos"]

            kind = combiV["kind"]
            textloc = combiV["textloc"]
            date = combiV["date"]

            featureFunc = (
                (lambda n: kind.get(n, None))
                if feature == "kind"
                else (lambda n: textloc.get(n, None))
                if feature == "textloc"
                else (lambda n: date.get(n, None))
                if feature == "date"
                else Fs(feature).v
            )

            value = featureFunc(node)
            if vMap:
                value = vMap.get(value, default)
            else:
                value = value or default

            afterVal = ""
            if afterFeature is not None:
                afterVal = Fs(afterFeature).v(node)
            if not afterVal and afterDefault:
                afterVal = afterDefault
            value = f"{value}{afterVal}"

            if pos is None:
                recorders[level][layer].add(value)
            else:
                accumulators[level][layer].append(value)

            if first:
                returnValue = value
                first = False

        return returnValue

    def addAfterValue(node):
        level = F.otype.v(node)
        typeInfo = layerSettings[level]
        value = typeInfo.get("afterDefault", None)
        if value:
            addAll(level, value)

    def addAll(level, value):
        lowerTypes = typesLower[level]
        for lType in lowerTypes:
            if lType in recorders:
                for x in recorders[lType].values():
                    x.add(value)
            if lType in accumulators:
                for x in accumulators[lType].values():
                    x.append(value)

    def addLevel(level, value):
        if level in recorders:
            for x in recorders[level].values():
                x.add(value)
        if level in accumulators:
            for x in accumulators[level].values():
                x.append(value)

    def addLayer(level, layer, value):
        if level in recorders:
            if layer in recorders[level]:
                recorders[level][layer].add(value)
        if level in accumulators:
            if layer in accumulators[level]:
                accumulators[level][layer].append(value)

    def startNode(node):
        # we have organized recorders by node type
        # we only record nodes of matching type in recorders

        level = F.otype.v(node)

        if level in recorders:
            for rec in recorders[level].values():
                rec.start(node)

    def endNode(node):
        # we have organized recorders by node type
        # we only record nodes of matching type in recorders
        level = F.otype.v(node)

        if level in recorders:
            for rec in recorders[level].values():
                rec.end(node)

    # note the `up[n] = m` statements below:
    # we only let `up` connect nodes from one level to one level higher

    for (i, volume) in enumerate(F.otype.s("volume")):
        startNode(volume)
        title = addValue(volume)
        sys.stdout.write("\r" + f"{i + 1:>3} {title:<80}")

        for letter in L.d(volume, otype="letter"):
            up[letter] = volume
            startNode(letter)
            addValue(letter)

            for line in L.d(letter, otype="line"):
                up[line] = letter
                startNode(line)
                addValue(line)

                for word in L.d(line, otype="word"):
                    up[word] = line
                    startNode(word)
                    addValue(word)
                    endNode(word)

                addAfterValue(line)
                endNode(line)
            addAfterValue(letter)
            endNode(letter)

        addAfterValue(volume)
        endNode(volume)

    sys.stdout.write("\n")
    A.info("done")

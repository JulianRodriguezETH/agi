import sys, os, collections
root = sys.argv[1]
for split in ("train", "valid", "test"):
    d = os.path.join(root, "labels", split)
    imgs = collections.Counter(); boxes = collections.Counter(); sizes = collections.defaultdict(list)
    percnt = []
    for f in os.listdir(d):
        cls_here = collections.Counter()
        with open(os.path.join(d, f)) as fh:
            for line in fh:
                p = line.split()
                if len(p) != 5: continue
                c = int(p[0]); cls_here[c] += 1
                sizes[c].append((float(p[3]), float(p[4])))
        for c, n in cls_here.items():
            imgs[c] += 1; boxes[c] += n
        if cls_here.get(1): percnt.append(cls_here[1])
    print(split, "imgs/clase", dict(sorted(imgs.items())), "cajas/clase", dict(sorted(boxes.items())))
    if percnt:
        percnt.sort()
        print("  reses por imagen: min", percnt[0], "mediana", percnt[len(percnt)//2], "max", percnt[-1])
    for c in sorted(sizes):
        w = sorted(s[0] for s in sizes[c]); h = sorted(s[1] for s in sizes[c])
        print("  clase", c, "ancho mediano %.3f alto mediano %.3f" % (w[len(w)//2], h[len(h)//2]))

class TagSet:
    MAX_VLAN = 4096
    VLAN_ANY_RANGE = "2-4094"

    def __init__(self, *, arange="2-4094"):
        self.avail = [False] * TagSet.MAX_VLAN

        range_list = arange.split(",")

        for part in range_list:
            stripped = part.strip()

            if stripped == "":
                continue

            range_ends = stripped.split("-")
            start = int(range_ends[0])
            end = int(range_ends[1])

            for k in range(start, end + 1):
                self.avail[k] = True

    def remove_tag(self, tag: int):
        self.avail[tag] = False

    def available_tag(self):
        avail = []
        for i in range(len(self.avail)):
            if self.avail[i]:
                avail.append(i)

        import random

        random.shuffle(avail)
        return avail[0] if avail else None

    def to_string(self):
        rep = ""
        start = 0

        for i in range(len(self.avail)):
            if self.avail[i]:
                start = i
                break

        if start < 2 or start == len(self.avail) - 1:
            return rep

        fragments = []
        fragment = [0] * 2
        fragment[0] = start
        fragment[1] = len(self.avail) - 1
        prev = True

        for i in range(start + 1, len(self.avail)):
            if prev != self.avail[i]:
                if prev:
                    fragment[1] = i - 1
                    fragments.append(fragment)
                else:
                    fragment = [0] * 2
                    fragment[0] = i

            prev = self.avail[i]

        for i, tmp in enumerate(fragments):
            rep += str(tmp[0]) + "-" + str(tmp[1])

            if i < len(fragments) - 1:
                rep += ","

        return rep


def get_available_vlan(*, stitch_port):
    if 'vlan_range' in stitch_port:
        import random
        import copy

        allocated_vlans = stitch_port['allocated_vlans'] if 'allocated_vlans' in stitch_port else []
        vlan_range = copy.deepcopy(stitch_port['vlan_range'])
        random.shuffle(vlan_range)

        for arange in vlan_range:
            tag_set = TagSet(arange=arange)

            for allocated_vlan in allocated_vlans:
                tag_set.remove_tag(allocated_vlan)

            tag = tag_set.available_tag()

            if tag:
                return tag

    raise Exception("No vlan_range .....")


if __name__ == "__main__":
    # tags = TagSet(arange="   2-10,    13-15")
    tags = TagSet(arange="2-2")
    tags.remove_tag(2)

    print("*********")
    print(tags.to_string())

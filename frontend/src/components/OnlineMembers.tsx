import type { Member } from "../api/types";

export default function OnlineMembers({ members }: { members: Member[] }) {
  if (members.length === 0) {
    return null;
  }

  const online = members.filter((member) => member.online);
  const offline = members.filter((member) => !member.online);

  return (
    <aside className="members">
      <h2 className="members__title">
        Members <span className="muted">({online.length} online)</span>
      </h2>
      <ul className="members__list">
        {online.map((member) => (
          <li key={member.id} className="members__item">
            <span className="dot dot--online" aria-hidden="true" />
            {member.username}
          </li>
        ))}
        {offline.map((member) => (
          <li key={member.id} className="members__item">
            <span className="dot" aria-hidden="true" />
            {member.username}
          </li>
        ))}
      </ul>
    </aside>
  );
}
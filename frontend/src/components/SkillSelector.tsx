import { useEffect, useMemo, useState } from 'react';
import { Form, Select, Tag, theme } from 'antd';

interface SkillSummary {
  template_key: string;
  template_name: string;
  description: string;
  category: string;
}

interface Props {
  value?: string;
  onChange?: (value?: string) => void;
  disabled?: boolean;
}

/** 大纲/编辑等弹窗共用的「应用 Skill」下拉：outline 置顶 + 推荐标注，其余按分类排序。 */
export default function SkillSelector({ value, onChange, disabled }: Props) {
  const { token } = theme.useToken();
  const [skills, setSkills] = useState<SkillSummary[]>([]);

  useEffect(() => {
    fetch('/api/skills/list')
      .then(r => (r.ok ? r.json() : []))
      .then((data: unknown) => {
        if (Array.isArray(data)) setSkills(data as SkillSummary[]);
      })
      .catch(() => setSkills([]));
  }, []);

  // outline 置顶（标注推荐），其余按分类 + 名称排序
  const sortedSkills = useMemo(() => {
    const list = [...skills];
    list.sort((a, b) => {
      const pa = a.template_key === 'SKILL_OUTLINE' ? 0 : 1;
      const pb = b.template_key === 'SKILL_OUTLINE' ? 0 : 1;
      if (pa !== pb) return pa - pb;
      return a.category.localeCompare(b.category, 'zh') || a.template_name.localeCompare(b.template_name, 'zh');
    });
    return list;
  }, [skills]);

  const selected = skills.find(s => s.template_key === value);

  return (
    <Form.Item label="应用 Skill" style={{ marginBottom: 8 }}>
      <Select
        placeholder="不使用 Skill（标准创作）"
        value={value}
        onChange={onChange}
        allowClear
        disabled={disabled}
        showSearch
        optionFilterProp="label"
      >
        {sortedSkills.map(skill => (
          <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
            <span>{skill.template_name}</span>
            {skill.template_key === 'SKILL_OUTLINE' && (
              <Tag color="blue" style={{ marginLeft: 8 }}>推荐</Tag>
            )}
            <Tag style={{ marginLeft: 8 }}>{skill.category}</Tag>
          </Select.Option>
        ))}
      </Select>
      {selected && (
        <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
          ✓ {selected.description}
        </div>
      )}
    </Form.Item>
  );
}
